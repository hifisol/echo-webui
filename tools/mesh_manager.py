"""MeshCore LoRa mesh manager — async-to-sync bridge for Flask."""

import asyncio
import json
import logging
import threading
import time
from queue import Queue, Empty

from core.database import execute_db, query_db
from core.events import event_bus

log = logging.getLogger(__name__)


class MeshManager:
    """Wraps the async meshcore library in a background thread with an asyncio
    event loop.  Flask routes put commands on a thread-safe queue; the async
    loop processes them and publishes SSE events back."""

    def __init__(self, db_path, serial_port="/dev/ttyUSB0", baud_rate=115200):
        self.db_path = db_path
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self._running = False
        self._connected = False
        self._thread = None
        self._loop = None
        self._meshcore = None
        self._cmd_queue = Queue()
        self._device_info = {}
        self._error = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def is_running(self):
        return self._running and self._connected

    @property
    def last_error(self):
        return self._error

    # ------------------------------------------------------------------
    # Lifecycle (called from Flask / sync context)
    # ------------------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._error = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._connected = False
        self._meshcore = None
        event_bus.publish("mesh", "device-status", {"connected": False})

    # ------------------------------------------------------------------
    # Command methods (called from Flask routes, thread-safe)
    # ------------------------------------------------------------------

    def send_message(self, contact_key, text):
        self._cmd_queue.put(("send_msg", {"contact_key": contact_key, "text": text}))

    def send_channel_message(self, channel_id, text):
        self._cmd_queue.put(("send_chan", {"channel_id": channel_id, "text": text}))

    def request_telemetry(self, contact_key):
        self._cmd_queue.put(("req_telemetry", {"contact_key": contact_key}))

    def set_device_config(self, name=None, lat=None, lon=None, tx_power=None):
        self._cmd_queue.put(("set_config", {
            "name": name, "lat": lat, "lon": lon, "tx_power": tx_power
        }))

    def send_advertisement(self, flood=False):
        self._cmd_queue.put(("advertise", {"flood": flood}))

    def refresh_contacts(self):
        self._cmd_queue.put(("get_contacts", {}))

    def refresh_device_info(self):
        self._cmd_queue.put(("device_query", {}))

    # ------------------------------------------------------------------
    # Background asyncio thread
    # ------------------------------------------------------------------

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as exc:
            log.error("Mesh loop crashed: %s", exc)
            self._error = str(exc)
            event_bus.publish("mesh", "error", {"error": str(exc)})
        finally:
            self._connected = False
            self._running = False

    async def _async_main(self):
        try:
            from meshcore import MeshCore, EventType
        except ImportError:
            self._error = "meshcore library not installed"
            event_bus.publish("mesh", "error", {"error": self._error})
            return

        # Connect
        try:
            self._meshcore = await MeshCore.create_serial(
                self.serial_port, self.baud_rate
            )
        except Exception as exc:
            self._error = f"Connection failed: {exc}"
            event_bus.publish("mesh", "error", {"error": self._error})
            return

        if self._meshcore is None:
            self._error = ("Device did not respond — is it flashed with "
                           "MeshCore companion firmware?")
            event_bus.publish("mesh", "error", {"error": self._error})
            return

        self._connected = True
        event_bus.publish("mesh", "device-status", {"connected": True})

        # Subscribe to events
        self._meshcore.subscribe(EventType.CONTACT_MSG_RECV, self._on_message_recv)
        self._meshcore.subscribe(EventType.ACK, self._on_ack)
        self._meshcore.subscribe(EventType.ADVERTISEMENT, self._on_advertisement)
        self._meshcore.subscribe(EventType.BATTERY, self._on_battery)
        self._meshcore.subscribe(EventType.DISCONNECTED, self._on_disconnect)

        # Start auto message fetching
        await self._meshcore.start_auto_message_fetching()

        # Get initial device info + contacts
        await self._fetch_device_info()
        await self._fetch_contacts()

        # Main loop: process command queue
        while self._running:
            try:
                cmd, args = self._cmd_queue.get_nowait()
                await self._handle_command(cmd, args)
            except Empty:
                pass
            await asyncio.sleep(0.1)

        # Cleanup
        try:
            await self._meshcore.stop_auto_message_fetching()
            await self._meshcore.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    async def _handle_command(self, cmd, args):
        from meshcore import EventType

        try:
            if cmd == "send_msg":
                contact = self._meshcore.get_contact_by_key_prefix(args["contact_key"])
                if not contact:
                    event_bus.publish("mesh", "error", {"error": f"Contact {args['contact_key']} not found"})
                    return
                result = await self._meshcore.commands.send_msg(contact, args["text"])
                if result.type == EventType.MSG_SENT:
                    ack_hex = result.payload.get("expected_ack", b"").hex() if isinstance(result.payload, dict) else ""
                    self._store_message("sent", "direct", None, args["contact_key"],
                                        None, args["text"], expected_ack=ack_hex)
                    event_bus.publish("mesh", "message", {
                        "direction": "sent", "type": "direct",
                        "to": args["contact_key"], "text": args["text"]
                    })

            elif cmd == "send_chan":
                result = await self._meshcore.commands.send_msg(args["channel_id"], args["text"])
                self._store_message("sent", "channel", None, None,
                                    args["channel_id"], args["text"])
                event_bus.publish("mesh", "message", {
                    "direction": "sent", "type": "channel",
                    "channel": args["channel_id"], "text": args["text"]
                })

            elif cmd == "get_contacts":
                await self._fetch_contacts()

            elif cmd == "device_query":
                await self._fetch_device_info()

            elif cmd == "req_telemetry":
                contact = self._meshcore.get_contact_by_key_prefix(args["contact_key"])
                if contact:
                    await self._meshcore.commands.send_msg(contact, "/telemetry")

            elif cmd == "set_config":
                if args.get("name"):
                    await self._meshcore.commands.set_name(args["name"])
                    self._update_device_state("name", args["name"])
                if args.get("tx_power") is not None:
                    await self._meshcore.commands.set_tx_power(int(args["tx_power"]))
                    self._update_device_state("tx_power", str(args["tx_power"]))
                event_bus.publish("mesh", "device-status", {"config_updated": True})

            elif cmd == "advertise":
                await self._meshcore.commands.send_advert(flood=args.get("flood", False))
                event_bus.publish("mesh", "device-status", {"advertised": True})

        except Exception as exc:
            log.error("Command %s failed: %s", cmd, exc)
            event_bus.publish("mesh", "error", {"error": f"{cmd}: {exc}"})

    # ------------------------------------------------------------------
    # Event handlers (called from async context)
    # ------------------------------------------------------------------

    def _on_message_recv(self, event):
        payload = event.payload if hasattr(event, "payload") else event
        try:
            from_id = payload.get("from", payload.get("pubkey_prefix", "unknown"))
            text = payload.get("text", payload.get("message", ""))
            snr = payload.get("snr")
            hop_count = payload.get("hops")

            self._store_message("received", "direct", from_id, None, None, text,
                                snr=snr, hop_count=hop_count)
            self._upsert_contact(from_id, snr=snr)

            event_bus.publish("mesh", "message", {
                "direction": "received", "type": "direct",
                "from": from_id, "text": text, "snr": snr
            })
        except Exception as exc:
            log.error("on_message_recv error: %s", exc)

    def _on_ack(self, event):
        payload = event.payload if hasattr(event, "payload") else event
        try:
            ack_hex = payload.get("ack", b"").hex() if isinstance(payload.get("ack"), bytes) else str(payload.get("ack", ""))
            execute_db(self.db_path,
                       "UPDATE mesh_messages SET ack_received=1 WHERE expected_ack=? AND ack_received=0",
                       (ack_hex,))
            event_bus.publish("mesh", "ack", {"ack": ack_hex})
        except Exception as exc:
            log.error("on_ack error: %s", exc)

    def _on_advertisement(self, event):
        payload = event.payload if hasattr(event, "payload") else event
        try:
            node_id = payload.get("pubkey_prefix", payload.get("from", "unknown"))
            name = payload.get("adv_name", payload.get("name"))
            lat = payload.get("adv_lat")
            lon = payload.get("adv_lon")
            self._upsert_contact(node_id, name=name, lat=lat, lon=lon)
            event_bus.publish("mesh", "contact-update", {
                "node_id": node_id, "name": name
            })
        except Exception as exc:
            log.error("on_advertisement error: %s", exc)

    def _on_battery(self, event):
        payload = event.payload if hasattr(event, "payload") else event
        try:
            level = payload.get("level", payload.get("battery"))
            voltage = payload.get("voltage")
            self._update_device_state("battery_level", str(level) if level else None)
            self._update_device_state("voltage", str(voltage) if voltage else None)
            event_bus.publish("mesh", "device-status", {
                "battery": level, "voltage": voltage
            })
        except Exception as exc:
            log.error("on_battery error: %s", exc)

    def _on_disconnect(self, event):
        self._connected = False
        event_bus.publish("mesh", "device-status", {"connected": False})

    # ------------------------------------------------------------------
    # Fetchers
    # ------------------------------------------------------------------

    async def _fetch_device_info(self):
        from meshcore import EventType
        try:
            result = await self._meshcore.commands.send_device_query()
            if result.type == EventType.DEVICE_INFO:
                info = result.payload if isinstance(result.payload, dict) else {}
                self._device_info = info
                for k, v in info.items():
                    self._update_device_state(k, str(v) if v is not None else None)
                event_bus.publish("mesh", "device-status", {"info": info, "connected": True})

            bat_result = await self._meshcore.commands.get_bat()
            if bat_result.type == EventType.BATTERY:
                self._on_battery(bat_result)
        except Exception as exc:
            log.error("fetch_device_info error: %s", exc)

    async def _fetch_contacts(self):
        from meshcore import EventType
        try:
            result = await self._meshcore.commands.get_contacts()
            if result.type == EventType.CONTACTS:
                contacts = result.payload if isinstance(result.payload, dict) else {}
                for key, contact in contacts.items():
                    name = contact.get("adv_name", contact.get("name"))
                    pub_key = contact.get("public_key", key)
                    lat = contact.get("adv_lat")
                    lon = contact.get("adv_lon")
                    node_id = pub_key[:12] if len(pub_key) > 12 else pub_key
                    self._upsert_contact(node_id, name=name, public_key=pub_key,
                                         lat=lat, lon=lon)
                event_bus.publish("mesh", "contact-update", {"refresh": True})
        except Exception as exc:
            log.error("fetch_contacts error: %s", exc)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _upsert_contact(self, node_id, name=None, public_key=None,
                        lat=None, lon=None, battery=None, snr=None, rssi=None):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        existing = query_db(self.db_path,
                            "SELECT id FROM mesh_contacts WHERE node_id=?",
                            (node_id,), one=True)
        if existing:
            parts, params = [], []
            if name is not None:
                parts.append("name=?"); params.append(name)
            if public_key is not None:
                parts.append("public_key=?"); params.append(public_key)
            if lat is not None:
                parts.append("latitude=?"); params.append(lat)
            if lon is not None:
                parts.append("longitude=?"); params.append(lon)
            if battery is not None:
                parts.append("battery_level=?"); params.append(battery)
            if snr is not None:
                parts.append("snr=?"); params.append(snr)
            if rssi is not None:
                parts.append("rssi=?"); params.append(rssi)
            parts.append("last_heard=?"); params.append(now)
            params.append(node_id)
            execute_db(self.db_path,
                       f"UPDATE mesh_contacts SET {','.join(parts)} WHERE node_id=?",
                       tuple(params))
        else:
            execute_db(self.db_path,
                       """INSERT INTO mesh_contacts
                          (node_id, name, public_key, latitude, longitude,
                           battery_level, snr, rssi, last_heard)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       (node_id, name, public_key, lat, lon, battery, snr, rssi, now))

    def _store_message(self, direction, msg_type, from_id, to_id,
                       channel_id, text, expected_ack=None, snr=None, hop_count=None):
        execute_db(self.db_path,
                   """INSERT INTO mesh_messages
                      (direction, message_type, from_node_id, to_node_id,
                       channel_id, message, expected_ack, snr, hop_count)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (direction, msg_type, from_id, to_id,
                    channel_id, text, expected_ack, snr, hop_count))

    def _update_device_state(self, key, value):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        execute_db(self.db_path,
                   """INSERT INTO mesh_device_state (key, value, updated_at)
                      VALUES (?,?,?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                      updated_at=excluded.updated_at""",
                   (key, value, now))

    def _store_telemetry(self, node_id, data):
        execute_db(self.db_path,
                   """INSERT INTO mesh_telemetry
                      (node_id, battery_level, voltage, temperature, humidity,
                       latitude, longitude, altitude)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (node_id,
                    data.get("battery"), data.get("voltage"),
                    data.get("temperature"), data.get("humidity"),
                    data.get("latitude"), data.get("longitude"),
                    data.get("altitude")))
