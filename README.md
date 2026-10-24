# R/P/T/R — Recon & Pentest Tactical Rig

Tactical RF dashboard for Raspberry Pi pentesting rigs. Built with Flask, HTMX, and Server-Sent Events for real-time updates. Dark tactical theme with red accent palette.

![R/P/T/R Dashboard](screenshot.png)

## Features

- **WiFi Recon** — Passive scanning via tshark with live AP/client/probe tables, signal tracking, and channel hopping
- **Attack Controls** — Deauth (aireplay-ng/mdk4), WPS (reaver/bully), handshake capture, nmap scanning, evil twin (hostapd/dnsmasq)
- **RTL-SDR Spectrum** — Spectrum analyzer with canvas waterfall display, frequency presets (WiFi, ISM, FM, ADS-B, AIS)
- **MeshCore LoRa Mesh** — LoRa mesh networking via MeshCore Python API — contacts, messaging, telemetry, device config
- **Job Queue** — Background task runner with live output streaming, cancel support, status tracking
- **System Status** — CPU, memory, disk, temperature, USB devices, wireless interface management

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python Flask + Gunicorn (gthread workers) |
| Frontend | HTMX + vanilla JS (spectrum canvas) |
| Real-time | Server-Sent Events |
| Database | SQLite (WAL mode) |
| Task runner | ThreadPoolExecutor + subprocess |
| Auth | Token-based with cookie sessions |

## Requirements

- Raspberry Pi (or any Linux box) with root access
- Python 3.10+
- WiFi adapter supporting monitor mode (e.g. RTL8812AU)
- RTL-SDR dongle (optional, for spectrum analysis)
- MeshCore LoRa board (optional, for mesh networking)
- Pentesting tools: `aircrack-ng`, `mdk4`, `tshark`, `nmap`, `reaver`, `hostapd`, `dnsmasq`, `rtl_power`

## Setup

```bash
# Clone
git clone https://github.com/hifisol/rptr-webui.git
cd rptr-webui

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp config.yaml.example config.yaml
# Edit config.yaml — set your auth token, bind address, interface name, etc.

# Initialize database
mkdir -p data
sqlite3 data/rptr.db < migrations/schema.sql

# Run (development)
python app.py

# Run (production)
gunicorn --bind 0.0.0.0:8443 --workers 2 --threads 4 --worker-class gthread --timeout 300 app:app
```

## Systemd Service

```bash
# Copy and edit the service file
sudo cp rptr-webui.service /etc/systemd/system/
# Edit bind address, paths as needed
sudo systemctl daemon-reload
sudo systemctl enable --now rptr-webui
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and customize:

| Setting | Description |
|---------|-------------|
| `auth.token` | Access token for authentication |
| `server.host` | Bind address (`0.0.0.0` for all interfaces) |
| `server.port` | Listen port (default `8443`) |
| `interfaces.wifi` | WiFi adapter name (e.g. `wlan0`) |
| `mesh.serial_port` | MeshCore LoRa serial device (e.g. `/dev/ttyUSB0`) |
| `mesh.enabled` | Enable/disable MeshCore integration |
| `sdr.device_index` | RTL-SDR device index |

## Playbooks

Repeatable workflows for the appliances in the RPTR stack live in [`Playbooks/`](Playbooks/README.md). The index lists each playbook and its status.

### Scanning Stack on the RPTR Scanner Host

The scanner host runs three tools. Placeholders: `<RPTR_HOST>` is the host's Tailscale address, `<NAME>` is an engagement name, and `<SITE_SLUG>` is a filename with no slashes.

**Access.** The host's web portals are reachable only from devices allowed by the Tailscale ACL, on these ports: `443` (GVM portal) and `8080` (DefectDojo). RDP (`3389`) and SSH (`22`) are allowed the same way. The host firewall (ufw) allows these ports only on the `tailscale0` interface. Passwords and secrets are stored on the host and never in this repo.

**GVM (host and network scans).**
- Runs as Greenbone Community Edition containers in `~/gvm-community/` (Docker Compose, project `greenbone-community-edition`). The override file `docker-compose.override.tailnet.yml` binds the portal to `<RPTR_HOST>:443`.
- Portal: `https://<RPTR_HOST>`. Accept the self-signed certificate. Log in as `admin`.
- Check the feeds first: **Administration > Feed Status**. Scans return nothing useful while the SCAP or NVT feed is still syncing.
- Create a target (**Configuration > Targets**), then a task (**Scans > Tasks**). Scan config **Full and fast** is the normal choice. **Discovery** finds hosts and services without vulnerability checks.
- Export the report and import it into DefectDojo as `OpenVAS`.

**Nuclei (website and web app checks).**
- Installed from the Parrot repository (`nuclei` 3.6.1). Check with `nuclei -version`.
- Run detached with `nohup` so a dropped SSH session doesn't stop it, and keep a log:
  ```bash
  mkdir -p ~/engagements/<NAME>/nuclei
  cd ~/engagements/<NAME>/nuclei
  nohup nuclei -u https://<SITE> -etags dos,fuzz -s medium,high,critical \
    -rl 10 -c 5 -timeout 10 -retries 1 -ni -stats \
    -jsonl -o <SITE_SLUG>.jsonl > <SITE_SLUG>-run.log 2>&1 < /dev/null &
  ```
- `-etags dos,fuzz` skips denial-of-service and fuzzing templates. `-ni` turns off out-of-band callbacks. Keep the rate low (`-rl`) unless you have agreed otherwise.
- The last line of the log reports the result (`Scan completed ... N matches found`).
- Import the `.jsonl` file into DefectDojo as `Nuclei Scan`.

**DefectDojo (findings tracking).**
- Runs from `~/defectdojo/` (DefectDojo Docker Compose). The override file `docker-compose.override.tailnet.yml` binds the web app to `<RPTR_HOST>:8080`.
- Settings live in `~/defectdojo/.env` (mode 600). It holds the secret key, the credential key, the database password, and the allowed hosts. Never commit this file. The upstream defaults are public, so the values must be replaced.
- Login: `http://<RPTR_HOST>:8080`, user `admin`. The first-boot password is in the initializer log (`docker compose logs initializer`).
- Structure: one product per site or client, one engagement per scan, then import the results and triage them (verified, false positive, accepted risk, fixed).

**Scope and rules.** Only scan systems you own or have written authorization to test. Keep engagement output out of git (the repo ignores `engagements/`, `*.jsonl`, `*.nessus`, and `*.burp`). Don't run a full GVM scan and a large Nuclei run at the same time on this host.

## Project Structure

```
rptr-webui/
├── app.py                  # Flask app factory + SSE endpoints
├── config.yaml.example     # Configuration template
├── rptr-webui.service      # systemd unit
├── requirements.txt
├── core/
│   ├── auth.py             # Token auth + rate limiting
│   ├── config.py           # YAML config loader
│   ├── database.py         # SQLite helpers (WAL mode)
│   ├── events.py           # SSE event bus (pub/sub)
│   └── tasks.py            # Background job runner
├── tools/
│   ├── wifi_scanner.py     # tshark passive scanning
│   ├── interface.py        # Monitor mode, channel, MAC
│   ├── mesh_manager.py     # MeshCore async-to-sync bridge
│   └── system.py           # System info (psutil)
├── blueprints/
│   ├── dashboard.py        # Overview page
│   ├── recon.py            # WiFi scanning
│   ├── attacks.py          # Attack controls
│   ├── sdr.py              # Spectrum analyzer
│   ├── mesh.py             # LoRa mesh networking
│   ├── jobs.py             # Job queue
│   └── system.py           # System status
├── templates/              # Jinja2 + HTMX partials
├── static/
│   ├── css/pager.css       # Dark tactical theme
│   └── js/
│       ├── app.js          # SSE handler, utilities
│       └── spectrum.js     # Canvas spectrum/waterfall
└── migrations/schema.sql   # SQLite schema
```

## Security Notes

- Runs as root (required for monitor mode, aircrack-ng, hostapd)
- All subprocess calls use argument lists (no `shell=True`)
- Input validation: BSSID regex, SSID sanitization, nmap flag whitelist
- Attack safety lock with confirmation dialogs
- Bind to a specific interface (Tailscale, VPN, localhost) rather than `0.0.0.0` in production
- Change the default auth token before deployment

## License

MIT
