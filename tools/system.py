import os
import subprocess

import psutil


def get_system_info():
    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    cpu_temp = entries[0].current
                    break
    except Exception:
        pass

    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    load = psutil.getloadavg()

    return {
        "hostname": os.uname().nodename,
        "uptime": int(psutil.boot_time()),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": psutil.cpu_count(),
        "cpu_temp": cpu_temp,
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_percent": mem.percent,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
        "load_1": load[0],
        "load_5": load[1],
        "load_15": load[2],
    }


def get_usb_devices():
    devices = []
    try:
        result = subprocess.run(
            ["lsusb"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if line and "Linux Foundation" not in line:
                devices.append(line.strip())
    except Exception:
        pass
    return devices


def get_network_interfaces():
    interfaces = []
    for name, addrs in psutil.net_if_addrs().items():
        if name == "lo":
            continue
        stats = psutil.net_if_stats().get(name)
        iface = {
            "name": name,
            "is_up": stats.isup if stats else False,
            "speed": stats.speed if stats else 0,
            "addrs": [],
        }
        for addr in addrs:
            if addr.family.name == "AF_INET":
                iface["addrs"].append({"type": "ipv4", "address": addr.address})
            elif addr.family.name == "AF_PACKET":
                iface["addrs"].append({"type": "mac", "address": addr.address})
        interfaces.append(iface)
    return interfaces


def get_wireless_info():
    info = {"adapter_present": False, "interface": None, "mode": None, "channel": None}
    try:
        result = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("Interface"):
                iface = line.split()[-1]
                if iface.startswith("wlan"):
                    info["adapter_present"] = True
                    info["interface"] = iface
            elif line.startswith("type"):
                info["mode"] = line.split()[-1]
            elif line.startswith("channel"):
                info["channel"] = line.split()[1]
    except Exception:
        pass
    return info
