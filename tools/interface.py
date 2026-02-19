import subprocess
import threading
import time


class InterfaceManager:
    def __init__(self):
        self._hopping = False
        self._hop_thread = None

    def set_monitor_mode(self, iface="wlan0"):
        try:
            subprocess.run(["ip", "link", "set", iface, "down"], check=True, capture_output=True)
            subprocess.run(["iw", iface, "set", "type", "monitor"], check=True, capture_output=True)
            subprocess.run(["ip", "link", "set", iface, "up"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def set_managed_mode(self, iface="wlan0"):
        self.stop_channel_hop()
        try:
            subprocess.run(["ip", "link", "set", iface, "down"], check=True, capture_output=True)
            subprocess.run(["iw", iface, "set", "type", "managed"], check=True, capture_output=True)
            subprocess.run(["ip", "link", "set", iface, "up"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def set_channel(self, iface, channel):
        try:
            subprocess.run(
                ["iw", "dev", iface, "set", "channel", str(channel)],
                check=True, capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def start_channel_hop(self, iface, channels=None, interval=0.5):
        if channels is None:
            channels = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 36, 40, 44, 48]
        self._hopping = True

        def hop():
            idx = 0
            while self._hopping:
                ch = channels[idx % len(channels)]
                self.set_channel(iface, ch)
                idx += 1
                time.sleep(interval)

        self._hop_thread = threading.Thread(target=hop, daemon=True)
        self._hop_thread.start()

    def stop_channel_hop(self):
        self._hopping = False
        if self._hop_thread:
            self._hop_thread.join(timeout=2)
            self._hop_thread = None

    def change_mac(self, iface, mac=None):
        try:
            subprocess.run(["ip", "link", "set", iface, "down"], check=True, capture_output=True)
            if mac:
                subprocess.run(["macchanger", "-m", mac, iface], check=True, capture_output=True)
            else:
                result = subprocess.run(
                    ["macchanger", "-r", iface], capture_output=True, text=True, check=True
                )
                for line in result.stdout.split("\n"):
                    if "New MAC" in line:
                        mac = line.split()[-1]
            subprocess.run(["ip", "link", "set", iface, "up"], check=True, capture_output=True)
            return mac
        except subprocess.CalledProcessError:
            return None

    def get_mode(self, iface="wlan0"):
        try:
            result = subprocess.run(
                ["iw", "dev", iface, "info"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if "type" in line:
                    return line.strip().split()[-1]
        except Exception:
            pass
        return "unknown"

    def is_available(self, iface="wlan0"):
        try:
            result = subprocess.run(
                ["ip", "link", "show", iface], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
