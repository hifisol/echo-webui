#!/usr/bin/env python3
"""MeshCore Chat Logger - Captures mesh messages from a MeshCore Server device via serial.

Writes raw logs to /var/log/meshcore/meshcore-YYYY-MM-DD.log
Writes structured JSONL to /var/log/meshcore/meshcore-YYYY-MM-DD.jsonl
Writes device status to /var/log/meshcore/device_status.json
"""

import json
import os
import re
import serial
import signal
import sys
import time
from datetime import datetime, timezone

SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200
LOG_DIR = "/var/log/meshcore"
RECONNECT_DELAY = 10

running = True


def signal_handler(sig, frame):
    global running
    print(f"[{now()}] Received signal {sig}, shutting down...")
    running = False


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log_filename():
    return os.path.join(LOG_DIR, datetime.now(timezone.utc).strftime("meshcore-%Y-%m-%d.log"))


def jsonl_filename():
    return os.path.join(LOG_DIR, datetime.now(timezone.utc).strftime("meshcore-%Y-%m-%d.jsonl"))


def write_log(line):
    path = log_filename()
    with open(path, "a") as f:
        f.write(f"[{now()}] {line}\n")
    print(f"[{now()}] {line}")


def write_jsonl(event_type, data):
    """Append a structured event to the daily JSONL file."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
    }
    record.update(data)
    path = jsonl_filename()
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def write_device_status(firmware_version=None, connected=True):
    """Write current device status to a JSON file for the web UI."""
    status = {
        "connected": connected,
        "firmware": firmware_version,
        "serial_port": SERIAL_PORT,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "logger_pid": os.getpid(),
    }
    path = os.path.join(LOG_DIR, "device_status.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp_path, path)


def parse_mesh_line(line):
    """Parse a raw mesh log line into a structured event.

    MeshCore server firmware log output formats (observed patterns):
      Messages:  "from <name>(<key>): <text>"
                 "ch<N> from <name>(<key>): <text>"
      Adverts:   "adv <name> <key> <lat> <lon>"
                 "ADV: <name> [<key>]"
      Telemetry: "bat: <pct>% <voltage>V"
                 "tel <key>: bat=<pct> volt=<v> temp=<t>"

    Returns (event_type, data_dict) or ("raw", {"line": line}) as fallback.
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Direct message: "from Name(abcdef123456): hello world"
    m = re.match(
        r'from\s+(.+?)\(([0-9a-fA-F]+)\):\s*(.*)', stripped
    )
    if m:
        return ("message", {
            "direction": "received",
            "message_type": "direct",
            "from_name": m.group(1).strip(),
            "from_node_id": m.group(2),
            "text": m.group(3),
        })

    # Channel message: "ch0 from Name(abcdef123456): hello"
    m = re.match(
        r'ch(\d+)\s+from\s+(.+?)\(([0-9a-fA-F]+)\):\s*(.*)', stripped
    )
    if m:
        return ("message", {
            "direction": "received",
            "message_type": "channel",
            "channel_id": int(m.group(1)),
            "from_name": m.group(2).strip(),
            "from_node_id": m.group(3),
            "text": m.group(4),
        })

    # Advertisement: "adv Name abcdef123456 41.8781 -87.6298"
    m = re.match(
        r'adv\s+(\S+)\s+([0-9a-fA-F]+)\s+([-\d.]+)\s+([-\d.]+)', stripped, re.IGNORECASE
    )
    if m:
        return ("advertisement", {
            "name": m.group(1),
            "node_id": m.group(2),
            "latitude": float(m.group(3)),
            "longitude": float(m.group(4)),
        })

    # Advertisement alt format: "ADV: Name [abcdef123456]"
    m = re.match(
        r'ADV:\s*(.+?)\s*\[([0-9a-fA-F]+)\]', stripped
    )
    if m:
        return ("advertisement", {
            "name": m.group(1).strip(),
            "node_id": m.group(2),
        })

    # Battery/telemetry: "bat: 85% 4.12V"
    m = re.match(
        r'bat:\s*(\d+)%\s*([\d.]+)V', stripped, re.IGNORECASE
    )
    if m:
        return ("telemetry", {
            "battery_level": int(m.group(1)),
            "voltage": float(m.group(2)),
        })

    # Telemetry with node: "tel abcdef: bat=85 volt=4.12 temp=23.5"
    m = re.match(
        r'tel\s+([0-9a-fA-F]+):\s*(.*)', stripped, re.IGNORECASE
    )
    if m:
        data = {"node_id": m.group(1)}
        pairs = m.group(2)
        for kv in re.findall(r'(\w+)=([\d.]+)', pairs):
            key, val = kv
            if key == "bat":
                data["battery_level"] = int(float(val))
            elif key == "volt":
                data["voltage"] = float(val)
            elif key == "temp":
                data["temperature"] = float(val)
            elif key == "hum":
                data["humidity"] = float(val)
            elif key == "lat":
                data["latitude"] = float(val)
            elif key == "lon":
                data["longitude"] = float(val)
            elif key == "alt":
                data["altitude"] = float(val)
        return ("telemetry", data)

    # SNR/RSSI info: "snr: 8.5 rssi: -65"
    m = re.match(r'snr:\s*([-\d.]+)', stripped, re.IGNORECASE)
    if m:
        data = {"snr": float(m.group(1))}
        rssi_m = re.search(r'rssi:\s*([-\d.]+)', stripped, re.IGNORECASE)
        if rssi_m:
            data["rssi"] = float(rssi_m.group(1))
        return ("signal", data)

    # Fallback: log as raw
    return ("raw", {"line": stripped})


def run():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    os.makedirs(LOG_DIR, exist_ok=True)
    write_log("MeshCore Logger starting")
    write_device_status(connected=False)
    write_jsonl("startup", {"message": "Logger starting", "pid": os.getpid()})

    while running:
        ser = None
        firmware_version = None
        try:
            write_log(f"Connecting to {SERIAL_PORT} at {BAUD_RATE} baud")
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5)
            time.sleep(2)

            # Get firmware version
            ser.write(b"ver\r\n")
            time.sleep(1)
            out = ser.read(ser.in_waiting or 256)
            ver_text = out.decode(errors="ignore").strip()
            write_log(f"Device: {ver_text}")

            # Extract version string
            m = re.search(r'v[\d.]+[-\w]*', ver_text)
            firmware_version = m.group(0) if m else ver_text
            write_jsonl("startup", {
                "message": "Connected",
                "firmware": firmware_version,
                "serial_port": SERIAL_PORT,
            })
            write_device_status(firmware_version=firmware_version, connected=True)

            # Sync clock
            utc_now = datetime.now(timezone.utc)
            clock_cmd = utc_now.strftime("clock set %H %M %d %m %Y")
            ser.write((clock_cmd + "\r\n").encode())
            time.sleep(1)
            out = ser.read(ser.in_waiting or 256)
            clock_text = out.decode(errors="ignore").strip()
            write_log(f"Clock sync: {clock_text}")
            write_jsonl("clock_sync", {"response": clock_text})

            # Enable live logging
            ser.write(b"log start\r\n")
            time.sleep(1)
            out = ser.read(ser.in_waiting or 256)
            write_log(f"Log mode: {out.decode(errors='ignore').strip()}")

            write_log("Listening for mesh messages...")

            # Main read loop
            while running:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    lines = data.decode(errors="ignore").strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        if line and line != "log start" and "logging on" not in line:
                            write_log(f"MESH: {line}")
                            parsed = parse_mesh_line(line)
                            if parsed:
                                event_type, event_data = parsed
                                write_jsonl(event_type, event_data)
                else:
                    time.sleep(0.5)

        except serial.SerialException as e:
            write_log(f"Serial error: {e}")
            write_jsonl("error", {"message": str(e)})
        except Exception as e:
            write_log(f"Error: {e}")
            write_jsonl("error", {"message": str(e)})
        finally:
            if ser and ser.is_open:
                try:
                    ser.write(b"log stop\r\n")
                    time.sleep(0.5)
                except Exception:
                    pass
                ser.close()
                write_log("Serial port closed")
            write_device_status(firmware_version=firmware_version, connected=False)

        if running:
            write_log(f"Reconnecting in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)

    write_log("MeshCore Logger stopped")
    write_device_status(connected=False)


if __name__ == "__main__":
    run()
