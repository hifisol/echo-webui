import re

from flask import Blueprint, render_template, request, current_app

bp = Blueprint("sdr", __name__, url_prefix="/sdr")

PRESETS = {
    "wifi_24": {"label": "WiFi 2.4GHz", "start": "2.4G", "end": "2.5G", "bin": "1M"},
    "wifi_5": {"label": "WiFi 5GHz", "start": "5.1G", "end": "5.9G", "bin": "2M"},
    "ism_433": {"label": "ISM 433MHz", "start": "433M", "end": "434M", "bin": "10k"},
    "ism_915": {"label": "ISM 915MHz", "start": "902M", "end": "928M", "bin": "100k"},
    "fm": {"label": "FM Radio", "start": "88M", "end": "108M", "bin": "100k"},
    "adsb": {"label": "ADS-B 1090MHz", "start": "1088M", "end": "1092M", "bin": "50k"},
    "ais": {"label": "AIS Marine", "start": "161.9M", "end": "162.1M", "bin": "10k"},
}

FREQ_RE = re.compile(r"^\d+(\.\d+)?[kMG]?$")


@bp.route("/")
def index():
    return render_template("sdr/spectrum.html", presets=PRESETS)


@bp.route("/api/start", methods=["POST"])
def start_sweep():
    runner = current_app.config["task_runner"]
    cfg = current_app.config["cfg"]

    preset = request.form.get("preset")
    if preset and preset in PRESETS:
        p = PRESETS[preset]
        freq_start = p["start"]
        freq_end = p["end"]
        bin_size = p["bin"]
    else:
        freq_start = request.form.get("freq_start", "").strip()
        freq_end = request.form.get("freq_end", "").strip()
        bin_size = request.form.get("bin_size", "1M").strip()

    if not FREQ_RE.match(freq_start) or not FREQ_RE.match(freq_end):
        return '<div class="alert alert-danger">Invalid frequency format</div>'

    device_idx = str(cfg["sdr"]["device_index"])
    cmd = [
        "rtl_power", "-f", f"{freq_start}:{freq_end}:{bin_size}",
        "-i", "1", "-1", "-d", device_idx,
    ]

    job_id = runner.submit("sdr_sweep", cmd)
    return f'<div class="alert alert-success">SDR sweep started (job {job_id})</div>'


@bp.route("/api/stop", methods=["POST"])
def stop_sweep():
    runner = current_app.config["task_runner"]
    jobs = runner.list_jobs(status="running")
    for job in jobs:
        if job["tool"] == "sdr_sweep":
            runner.cancel(job["id"])
    return '<div class="alert alert-info">SDR sweep stopped</div>'


@bp.route("/api/presets")
def get_presets():
    return render_template("sdr/_presets.html", presets=PRESETS)
