import re

from flask import Blueprint, render_template, request, current_app

from core.database import query_db, execute_db

bp = Blueprint("recon", __name__, url_prefix="/recon")


@bp.route("/")
def index():
    return render_template("recon/scan.html")


@bp.route("/api/start", methods=["POST"])
def start_scan():
    scanner = current_app.config.get("wifi_scanner")
    if not scanner:
        return '<div class="alert alert-danger">Scanner not initialized</div>'
    scanner.start()
    return '<div class="alert alert-success">Scan started</div>'


@bp.route("/api/stop", methods=["POST"])
def stop_scan():
    scanner = current_app.config.get("wifi_scanner")
    if scanner:
        scanner.stop()
    return '<div class="alert alert-info">Scan stopped</div>'


@bp.route("/api/aps")
def ap_table():
    db_path = current_app.config["cfg"]["database"]["path"]
    sort = request.args.get("sort", "signal_dbm")
    order = request.args.get("order", "desc")
    search = request.args.get("search", "")

    allowed_sorts = {"ssid", "bssid", "channel", "signal_dbm", "encryption", "client_count", "last_seen"}
    if sort not in allowed_sorts:
        sort = "signal_dbm"
    if order not in ("asc", "desc"):
        order = "desc"

    if search:
        aps = query_db(
            db_path,
            f"SELECT * FROM access_points WHERE ssid LIKE ? OR bssid LIKE ? ORDER BY {sort} {order}",
            (f"%{search}%", f"%{search}%"),
        )
    else:
        aps = query_db(db_path, f"SELECT * FROM access_points ORDER BY {sort} {order}")
    return render_template("recon/_ap_table.html", aps=aps, sort=sort, order=order)


@bp.route("/api/clients")
def client_table():
    db_path = current_app.config["cfg"]["database"]["path"]
    bssid = request.args.get("bssid")
    if bssid:
        clients = query_db(
            db_path,
            "SELECT * FROM clients WHERE associated_bssid = ? ORDER BY last_seen DESC",
            (bssid,),
        )
    else:
        clients = query_db(db_path, "SELECT * FROM clients ORDER BY last_seen DESC")
    return render_template("recon/_client_table.html", clients=clients)


@bp.route("/api/probes")
def probe_table():
    db_path = current_app.config["cfg"]["database"]["path"]
    mac = request.args.get("mac")
    if mac:
        probes = query_db(
            db_path,
            "SELECT * FROM probe_requests WHERE client_mac = ? ORDER BY timestamp DESC LIMIT 100",
            (mac,),
        )
    else:
        probes = query_db(
            db_path,
            "SELECT * FROM probe_requests ORDER BY timestamp DESC LIMIT 100",
        )
    return render_template("recon/_probe_table.html", probes=probes)
