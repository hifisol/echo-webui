"""MeshCore log reader — reads structured JSONL from the logger service.

Replaces MeshManager for server-firmware devices where the meshcore-logger
service owns the serial port. The web UI operates in read-only mode, tailing
JSONL files and populating the same database tables.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from core.database import execute_db, query_db

log = logging.getLogger(__name__)


class MeshReader:
    """Tails MeshCore JSONL log files written by meshcore_logger.py and
    inserts structured events into the web UI database."""

    def __init__(self, db_path, log_dir="/var/log/meshcore", poll_interval=2.0):
        self.db_path = db_path
        self.log_dir = log_dir
        self.poll_interval = poll_interval
        self._status_file = os.path.join(log_dir, "device_status.json")
        self._running = False
        self._thread = None
        self._file_positions = {}  # {filepath: byte_offset}
        self._current_file = None

    # ------------------------------------------------------------------
    # Public properties (matching MeshManager interface)
    # ------------------------------------------------------------------

    @property
    def is_running(self):
        return self._running

    @property
    def last_error(self):
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info("MeshReader started — tailing %s", self.log_dir)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        log.info("MeshReader stopped")

    # ------------------------------------------------------------------
    # Device status (read from logger's JSON file)
    # ------------------------------------------------------------------

    def get_device_status(self):
        """Read device_status.json written by the logger service."""
        try:
            with open(self._status_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"connected": False, "firmware": None}

    # ------------------------------------------------------------------
    # Background polling
    # ------------------------------------------------------------------

    def _poll_loop(self):
        while self._running:
            try:
                self._process_new_events()
            except Exception as exc:
                log.error("MeshReader poll error: %s", exc)
            time.sleep(self.poll_interval)

    def _process_new_events(self):
        """Read new lines from today's JSONL file."""
        today = datetime.now(timezone.utc).strftime("meshcore-%Y-%m-%d.jsonl")
        jsonl_path = os.path.join(self.log_dir, today)

        if not os.path.exists(jsonl_path):
            return

        # If the file changed (new day), reset position
        if self._current_file != jsonl_path:
            self._current_file = jsonl_path
            # Start from end of file on first run to avoid replaying old data
            if jsonl_path not in self._file_positions:
                self._file_positions[jsonl_path] = os.path.getsize(jsonl_path)

        last_pos = self._file_positions.get(jsonl_path, 0)

        with open(jsonl_path) as f:
            f.seek(last_pos)
            new_lines = f.readlines()
            self._file_positions[jsonl_path] = f.tell()

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                self._handle_event(event)
            except json.JSONDecodeError:
                log.warning("Bad JSONL line: %s", line[:100])

    def _handle_event(self, event):
        """Dispatch a structured event to the appropriate DB handler."""
        etype = event.get("type", "raw")

        if etype == "message":
            self._store_message(event)
        elif etype == "advertisement":
            self._upsert_contact(event)
        elif etype == "telemetry":
            self._store_telemetry(event)
        elif etype == "signal":
            self._update_signal(event)
        elif etype == "startup":
            self._update_startup(event)

    # ------------------------------------------------------------------
    # Database helpers (mirroring MeshManager's DB methods)
    # ------------------------------------------------------------------

    def _store_message(self, event):
        ts = event.get("ts", datetime.now(timezone.utc).isoformat())
        from_id = event.get("from_node_id")
        from_name = event.get("from_name")

        # Upsert the contact if we have a from_node_id
        if from_id:
            self._upsert_contact({
                "node_id": from_id,
                "name": from_name,
            })

        execute_db(self.db_path,
                   """INSERT INTO mesh_messages
                      (direction, message_type, from_node_id, to_node_id,
                       channel_id, message, snr, hop_count)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (event.get("direction", "received"),
                    event.get("message_type", "direct"),
                    from_id,
                    event.get("to_node_id"),
                    event.get("channel_id"),
                    event.get("text", ""),
                    event.get("snr"),
                    event.get("hop_count")))

    def _upsert_contact(self, event):
        node_id = event.get("node_id")
        if not node_id:
            return

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        existing = query_db(self.db_path,
                            "SELECT id FROM mesh_contacts WHERE node_id=?",
                            (node_id,), one=True)

        name = event.get("name")
        lat = event.get("latitude")
        lon = event.get("longitude")

        if existing:
            parts, params = [], []
            if name is not None:
                parts.append("name=?"); params.append(name)
            if lat is not None:
                parts.append("latitude=?"); params.append(lat)
            if lon is not None:
                parts.append("longitude=?"); params.append(lon)
            parts.append("last_heard=?"); params.append(now)
            params.append(node_id)
            execute_db(self.db_path,
                       f"UPDATE mesh_contacts SET {','.join(parts)} WHERE node_id=?",
                       tuple(params))
        else:
            execute_db(self.db_path,
                       """INSERT INTO mesh_contacts
                          (node_id, name, latitude, longitude, last_heard)
                          VALUES (?,?,?,?,?)""",
                       (node_id, name, lat, lon, now))

    def _store_telemetry(self, event):
        node_id = event.get("node_id")

        # If no node_id, this is local device telemetry
        if not node_id:
            if event.get("battery_level") is not None:
                self._update_device_state("battery_level", str(event["battery_level"]))
            if event.get("voltage") is not None:
                self._update_device_state("voltage", str(event["voltage"]))
            return

        execute_db(self.db_path,
                   """INSERT INTO mesh_telemetry
                      (node_id, battery_level, voltage, temperature, humidity,
                       latitude, longitude, altitude)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (node_id,
                    event.get("battery_level"),
                    event.get("voltage"),
                    event.get("temperature"),
                    event.get("humidity"),
                    event.get("latitude"),
                    event.get("longitude"),
                    event.get("altitude")))

        # Also update the contact's battery if we have it
        if event.get("battery_level") is not None:
            existing = query_db(self.db_path,
                                "SELECT id FROM mesh_contacts WHERE node_id=?",
                                (node_id,), one=True)
            if existing:
                execute_db(self.db_path,
                           "UPDATE mesh_contacts SET battery_level=? WHERE node_id=?",
                           (event["battery_level"], node_id))

    def _update_signal(self, event):
        """Update SNR/RSSI on the most recent contact."""
        snr = event.get("snr")
        rssi = event.get("rssi")
        if snr is not None:
            # Update the most recently heard contact
            recent = query_db(self.db_path,
                              "SELECT node_id FROM mesh_contacts ORDER BY last_heard DESC LIMIT 1",
                              one=True)
            if recent:
                parts, params = [], []
                parts.append("snr=?"); params.append(snr)
                if rssi is not None:
                    parts.append("rssi=?"); params.append(rssi)
                params.append(recent["node_id"])
                execute_db(self.db_path,
                           f"UPDATE mesh_contacts SET {','.join(parts)} WHERE node_id=?",
                           tuple(params))

    def _update_startup(self, event):
        fw = event.get("firmware")
        if fw:
            self._update_device_state("firmware", fw)

    def _update_device_state(self, key, value):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        execute_db(self.db_path,
                   """INSERT INTO mesh_device_state (key, value, updated_at)
                      VALUES (?,?,?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                      updated_at=excluded.updated_at""",
                   (key, value, now))
