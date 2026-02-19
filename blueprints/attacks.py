import re

from flask import Blueprint, render_template, request, current_app, session

bp = Blueprint("attacks", __name__, url_prefix="/attacks")

BSSID_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ALLOWED_NMAP_FLAGS = {"-sS", "-sT", "-sV", "-sC", "-sU", "-sn", "-Pn", "-O", "-A",
                      "--top-ports", "-p", "-T1", "-T2", "-T3", "-T4", "-F"}


def _validate_bssid(bssid):
    return bool(bssid and BSSID_RE.match(bssid))


def _is_unlocked():
    return session.get("safety_unlocked", False)


@bp.route("/")
def index():
    return render_template("attacks/index.html", unlocked=_is_unlocked())


@bp.route("/api/toggle-safety", methods=["POST"])
def toggle_safety():
    session["safety_unlocked"] = not session.get("safety_unlocked", False)
    return render_template("attacks/index.html", unlocked=session["safety_unlocked"])


@bp.route("/api/deauth", methods=["POST"])
def deauth():
    if not _is_unlocked():
        return '<div class="alert alert-danger">Safety lock is ON. Unlock first.</div>'

    runner = current_app.config["task_runner"]
    cfg = current_app.config["cfg"]
    iface = cfg["interfaces"]["wifi"]

    bssid = request.form.get("bssid", "").strip()
    client = request.form.get("client_mac", "").strip()
    count = request.form.get("count", "10").strip()

    if not _validate_bssid(bssid):
        return '<div class="alert alert-danger">Invalid BSSID</div>'
    if client and not _validate_bssid(client):
        return '<div class="alert alert-danger">Invalid client MAC</div>'

    try:
        count = min(int(count), 100)
    except ValueError:
        count = 10

    cmd = ["aireplay-ng", "-0", str(count), "-a", bssid]
    if client:
        cmd.extend(["-c", client])
    cmd.append(iface)

    job_id = runner.submit("deauth", cmd)
    return f'<div class="alert alert-success">Deauth started (job {job_id})</div>'


@bp.route("/api/handshake", methods=["POST"])
def capture_handshake():
    if not _is_unlocked():
        return '<div class="alert alert-danger">Safety lock is ON.</div>'

    runner = current_app.config["task_runner"]
    cfg = current_app.config["cfg"]
    iface = cfg["interfaces"]["wifi"]

    bssid = request.form.get("bssid", "").strip()
    channel = request.form.get("channel", "").strip()

    if not _validate_bssid(bssid):
        return '<div class="alert alert-danger">Invalid BSSID</div>'

    capture_dir = cfg["captures"]["dir"]
    prefix = f"{capture_dir}/hs_{bssid.replace(':', '')}"

    cmd = ["airodump-ng", "-c", channel, "--bssid", bssid, "-w", prefix, iface]
    job_id = runner.submit("handshake", cmd)
    return f'<div class="alert alert-success">Handshake capture started (job {job_id})</div>'


@bp.route("/api/wps", methods=["POST"])
def wps_attack():
    if not _is_unlocked():
        return '<div class="alert alert-danger">Safety lock is ON.</div>'

    runner = current_app.config["task_runner"]
    cfg = current_app.config["cfg"]
    iface = cfg["interfaces"]["wifi"]

    bssid = request.form.get("bssid", "").strip()
    tool = request.form.get("tool", "reaver").strip()

    if not _validate_bssid(bssid):
        return '<div class="alert alert-danger">Invalid BSSID</div>'
    if tool not in ("reaver", "bully"):
        return '<div class="alert alert-danger">Invalid tool</div>'

    if tool == "reaver":
        cmd = ["reaver", "-i", iface, "-b", bssid, "-vv"]
    else:
        cmd = ["bully", iface, "-b", bssid, "-v", "3"]

    job_id = runner.submit("wps", cmd)
    return f'<div class="alert alert-success">WPS attack started (job {job_id})</div>'


@bp.route("/api/nmap", methods=["POST"])
def nmap_scan():
    if not _is_unlocked():
        return '<div class="alert alert-danger">Safety lock is ON.</div>'

    runner = current_app.config["task_runner"]
    target = request.form.get("target", "").strip()
    flags = request.form.get("flags", "-sV").strip().split()

    if not target:
        return '<div class="alert alert-danger">No target specified</div>'

    for flag in flags:
        base_flag = flag.split("=")[0] if "=" in flag else flag
        if base_flag not in ALLOWED_NMAP_FLAGS and not re.match(r"^\d+(-\d+)?(,\d+(-\d+)?)*$", flag):
            return f'<div class="alert alert-danger">Disallowed flag: {flag}</div>'

    cmd = ["nmap"] + flags + [target]
    job_id = runner.submit("nmap", cmd)
    return f'<div class="alert alert-success">Nmap scan started (job {job_id})</div>'


@bp.route("/api/eviltwin", methods=["POST"])
def evil_twin():
    if not _is_unlocked():
        return '<div class="alert alert-danger">Safety lock is ON.</div>'
    return '<div class="alert alert-info">Evil twin - coming soon</div>'
