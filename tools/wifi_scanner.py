import re
import subprocess
import threading
import time

from core.database import execute_db, query_db
from core.events import event_bus
from tools.interface import InterfaceManager


class WiFiScanner:
    def __init__(self, db_path, iface="wlan0", channels=None, hop_interval=0.5):
        self.db_path = db_path
        self.iface = iface
        self.channels = channels or [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 36, 40, 44, 48]
        self.hop_interval = hop_interval
        self.interface_mgr = InterfaceManager()
        self._running = False
        self._process = None
        self._thread = None

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return
        if not self.interface_mgr.is_available(self.iface):
            return

        self.interface_mgr.set_monitor_mode(self.iface)
        self.interface_mgr.start_channel_hop(self.iface, self.channels, self.hop_interval)

        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                pass
            self._process = None
        self.interface_mgr.stop_channel_hop()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _scan_loop(self):
        cmd = [
            "tshark", "-i", self.iface, "-I",
            "-f", "type mgt",
            "-T", "fields",
            "-e", "wlan.sa",
            "-e", "wlan.da",
            "-e", "wlan.bssid",
            "-e", "wlan.ssid",
            "-e", "radiotap.dbm_antsignal",
            "-e", "wlan.fc.type_subtype",
            "-e", "wlan_radio.channel",
            "-e", "wlan.rsn.pcs.type",
            "-E", "separator=|",
            "-l",
        ]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
            )

            for line in self._process.stdout:
                if not self._running:
                    break
                self._parse_line(line.strip())

        except Exception:
            pass
        finally:
            self._running = False

    def _parse_line(self, line):
        if not line:
            return

        parts = line.split("|")
        if len(parts) < 6:
            return

        sa = parts[0].strip()
        da = parts[1].strip()
        bssid = parts[2].strip()
        ssid = parts[3].strip()
        signal = parts[4].strip()
        subtype = parts[5].strip()
        channel = parts[6].strip() if len(parts) > 6 else ""
        encryption = parts[7].strip() if len(parts) > 7 else ""

        try:
            signal_dbm = int(signal.split(",")[0]) if signal else None
        except (ValueError, IndexError):
            signal_dbm = None

        try:
            channel_num = int(channel.split(",")[0]) if channel else None
        except (ValueError, IndexError):
            channel_num = None

        enc_str = self._parse_encryption(encryption)

        # Beacon frame (subtype 8) or probe response (subtype 5)
        if subtype in ("0x0008", "8", "0x0005", "5") and bssid:
            self._upsert_ap(bssid, ssid, channel_num, signal_dbm, enc_str)

        # Probe request (subtype 4) - client probing
        if subtype in ("0x0004", "4") and sa:
            self._upsert_client(sa, None, signal_dbm)
            if ssid:
                self._record_probe(sa, ssid, signal_dbm)

        # Data frames or association - client associated to AP
        if sa and bssid and sa != bssid:
            self._upsert_client(sa, bssid, signal_dbm)

    def _parse_encryption(self, enc_raw):
        if not enc_raw:
            return "Open"
        enc_raw = enc_raw.lower()
        if "ccmp" in enc_raw or "aes" in enc_raw:
            return "WPA2"
        if "tkip" in enc_raw:
            return "WPA"
        return "WPA2" if enc_raw else "Open"

    def _upsert_ap(self, bssid, ssid, channel, signal_dbm, encryption):
        try:
            existing = query_db(
                self.db_path,
                "SELECT * FROM access_points WHERE bssid = ?",
                (bssid,),
                one=True,
            )

            if existing:
                updates = ["last_seen = CURRENT_TIMESTAMP"]
                params = []
                if signal_dbm is not None:
                    updates.append("signal_dbm = ?")
                    params.append(signal_dbm)
                    if existing["signal_min"] is None or signal_dbm < existing["signal_min"]:
                        updates.append("signal_min = ?")
                        params.append(signal_dbm)
                    if existing["signal_max"] is None or signal_dbm > existing["signal_max"]:
                        updates.append("signal_max = ?")
                        params.append(signal_dbm)
                if ssid and not existing["ssid"]:
                    updates.append("ssid = ?")
                    params.append(ssid)
                if channel:
                    updates.append("channel = ?")
                    params.append(channel)
                if encryption != "Open":
                    updates.append("encryption = ?")
                    params.append(encryption)

                params.append(bssid)
                execute_db(
                    self.db_path,
                    f"UPDATE access_points SET {', '.join(updates)} WHERE bssid = ?",
                    params,
                )
            else:
                execute_db(
                    self.db_path,
                    """INSERT INTO access_points (bssid, ssid, channel, signal_dbm, signal_min, signal_max, encryption)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (bssid, ssid or "", channel, signal_dbm, signal_dbm, signal_dbm, encryption),
                )

            event_bus.publish("scan", "ap-update", {
                "bssid": bssid, "ssid": ssid, "channel": channel,
                "signal_dbm": signal_dbm, "encryption": encryption,
            })
        except Exception:
            pass

    def _upsert_client(self, mac, bssid, signal_dbm):
        try:
            existing = query_db(
                self.db_path, "SELECT * FROM clients WHERE mac = ?", (mac,), one=True
            )
            if existing:
                updates = ["last_seen = CURRENT_TIMESTAMP"]
                params = []
                if signal_dbm is not None:
                    updates.append("signal_dbm = ?")
                    params.append(signal_dbm)
                if bssid:
                    updates.append("associated_bssid = ?")
                    params.append(bssid)
                params.append(mac)
                execute_db(
                    self.db_path,
                    f"UPDATE clients SET {', '.join(updates)} WHERE mac = ?",
                    params,
                )
            else:
                execute_db(
                    self.db_path,
                    "INSERT INTO clients (mac, associated_bssid, signal_dbm) VALUES (?, ?, ?)",
                    (mac, bssid, signal_dbm),
                )

            # Update client count on AP
            if bssid:
                execute_db(
                    self.db_path,
                    """UPDATE access_points SET client_count = (
                         SELECT COUNT(*) FROM clients WHERE associated_bssid = ?
                       ) WHERE bssid = ?""",
                    (bssid, bssid),
                )

            event_bus.publish("scan", "client-update", {
                "mac": mac, "bssid": bssid, "signal_dbm": signal_dbm,
            })
        except Exception:
            pass

    def _record_probe(self, client_mac, ssid, signal_dbm):
        try:
            execute_db(
                self.db_path,
                "INSERT INTO probe_requests (client_mac, ssid, signal_dbm) VALUES (?, ?, ?)",
                (client_mac, ssid, signal_dbm),
            )
        except Exception:
            pass
