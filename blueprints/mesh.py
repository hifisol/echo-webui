"""MeshCore LoRa mesh blueprint — UI + API routes."""

from flask import Blueprint, render_template, request, current_app
from core.database import query_db, execute_db

bp = Blueprint("mesh", __name__, url_prefix="/mesh")


def _mgr():
    return current_app.config.get("mesh_manager")


def _db():
    return current_app.config["cfg"]["database"]["path"]


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

@bp.route("/")
def index():
    db_path = _db()
    contact_count = query_db(db_path, "SELECT COUNT(*) AS c FROM mesh_contacts", one=True)
    msg_count = query_db(db_path, "SELECT COUNT(*) AS c FROM mesh_messages", one=True)
    mgr = _mgr()
    return render_template("mesh/index.html",
                           connected=mgr.is_running if mgr else False,
                           contact_count=contact_count["c"] if contact_count else 0,
                           message_count=msg_count["c"] if msg_count else 0)


# ------------------------------------------------------------------
# Connection API
# ------------------------------------------------------------------

@bp.route("/api/connect", methods=["POST"])
def connect():
    mgr = _mgr()
    if not mgr:
        return '<div class="alert alert-danger">Mesh manager not configured</div>'
    if mgr.is_running:
        return '<div class="alert alert-info">Already connected</div>'
    mgr.start()
    return '<div class="alert alert-success">Connecting to mesh device...</div>'


@bp.route("/api/disconnect", methods=["POST"])
def disconnect():
    mgr = _mgr()
    if mgr:
        mgr.stop()
    return '<div class="alert alert-info">Disconnected</div>'


# ------------------------------------------------------------------
# Device status
# ------------------------------------------------------------------

@bp.route("/api/status")
def status():
    mgr = _mgr()
    db_path = _db()
    rows = query_db(db_path, "SELECT key, value FROM mesh_device_state")
    state = {r["key"]: r["value"] for r in rows} if rows else {}
    return render_template("mesh/_device_status.html",
                           connected=mgr.is_running if mgr else False,
                           state=state,
                           error=mgr.last_error if mgr else None)


# ------------------------------------------------------------------
# Contacts
# ------------------------------------------------------------------

@bp.route("/api/contacts")
def contacts():
    db_path = _db()
    sort = request.args.get("sort", "last_heard")
    order = request.args.get("order", "desc")
    allowed = {"name", "node_id", "last_heard", "battery_level", "snr"}
    if sort not in allowed:
        sort = "last_heard"
    order = "DESC" if order.lower() == "desc" else "ASC"

    rows = query_db(db_path,
                     f"SELECT * FROM mesh_contacts ORDER BY {sort} {order}")
    return render_template("mesh/_contact_table.html", contacts=rows or [])


@bp.route("/api/contact/<node_id>")
def contact_detail(node_id):
    db_path = _db()
    contact = query_db(db_path,
                        "SELECT * FROM mesh_contacts WHERE node_id=?",
                        (node_id,), one=True)
    messages = query_db(db_path,
                         """SELECT * FROM mesh_messages
                            WHERE from_node_id=? OR to_node_id=?
                            ORDER BY timestamp DESC LIMIT 50""",
                         (node_id, node_id))
    telemetry = query_db(db_path,
                          """SELECT * FROM mesh_telemetry
                             WHERE node_id=? ORDER BY timestamp DESC LIMIT 20""",
                          (node_id,))
    return render_template("mesh/_contact_detail.html",
                           contact=contact, messages=messages or [],
                           telemetry=telemetry or [])


@bp.route("/api/refresh_contacts", methods=["POST"])
def refresh_contacts():
    mgr = _mgr()
    if mgr and mgr.is_running:
        mgr.refresh_contacts()
        return '<div class="alert alert-success">Refreshing contacts...</div>'
    return '<div class="alert alert-danger">Not connected</div>'


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------

@bp.route("/api/messages")
def messages():
    db_path = _db()
    msg_type = request.args.get("type", "all")
    node_id = request.args.get("node_id")

    query = "SELECT * FROM mesh_messages WHERE 1=1"
    params = []
    if msg_type in ("direct", "channel"):
        query += " AND message_type=?"
        params.append(msg_type)
    if node_id:
        query += " AND (from_node_id=? OR to_node_id=?)"
        params.extend([node_id, node_id])
    query += " ORDER BY timestamp DESC LIMIT 100"

    rows = query_db(db_path, query, params)
    return render_template("mesh/_message_list.html", messages=rows or [])


@bp.route("/api/send", methods=["POST"])
def send_message():
    mgr = _mgr()
    if not mgr or not mgr.is_running:
        return '<div class="alert alert-danger">Not connected</div>'

    contact_key = request.form.get("contact_key", "").strip()
    text = request.form.get("message", "").strip()
    if not contact_key or not text:
        return '<div class="alert alert-danger">Contact and message required</div>'
    if len(text) > 230:
        return '<div class="alert alert-danger">Message too long (max 230 chars)</div>'

    mgr.send_message(contact_key, text)
    return '<div class="alert alert-success">Message queued</div>'


@bp.route("/api/send_channel", methods=["POST"])
def send_channel():
    mgr = _mgr()
    if not mgr or not mgr.is_running:
        return '<div class="alert alert-danger">Not connected</div>'

    channel = request.form.get("channel", "0")
    text = request.form.get("message", "").strip()
    if not text:
        return '<div class="alert alert-danger">Message required</div>'
    if len(text) > 230:
        return '<div class="alert alert-danger">Message too long (max 230 chars)</div>'

    try:
        mgr.send_channel_message(int(channel), text)
    except (ValueError, TypeError):
        return '<div class="alert alert-danger">Invalid channel</div>'
    return '<div class="alert alert-success">Broadcast queued</div>'


# ------------------------------------------------------------------
# Telemetry
# ------------------------------------------------------------------

@bp.route("/api/request_telemetry", methods=["POST"])
def request_telemetry():
    mgr = _mgr()
    if not mgr or not mgr.is_running:
        return '<div class="alert alert-danger">Not connected</div>'
    node_key = request.form.get("contact_key", "").strip()
    if not node_key:
        return '<div class="alert alert-danger">Contact key required</div>'
    mgr.request_telemetry(node_key)
    return '<div class="alert alert-success">Telemetry requested</div>'


# ------------------------------------------------------------------
# Device config
# ------------------------------------------------------------------

@bp.route("/api/config", methods=["GET", "POST"])
def device_config():
    if request.method == "POST":
        mgr = _mgr()
        if not mgr or not mgr.is_running:
            return '<div class="alert alert-danger">Not connected</div>'

        name = request.form.get("name", "").strip() or None
        tx_power = request.form.get("tx_power", "").strip() or None

        try:
            if tx_power is not None:
                tx_power = int(tx_power)
        except ValueError:
            return '<div class="alert alert-danger">Invalid TX power</div>'

        mgr.set_device_config(name=name, tx_power=tx_power)
        return '<div class="alert alert-success">Configuration update queued</div>'

    db_path = _db()
    rows = query_db(db_path, "SELECT key, value FROM mesh_device_state")
    config = {r["key"]: r["value"] for r in rows} if rows else {}
    return render_template("mesh/_device_config.html", config=config)


# ------------------------------------------------------------------
# Advertisement
# ------------------------------------------------------------------

@bp.route("/api/advertise", methods=["POST"])
def advertise():
    mgr = _mgr()
    if not mgr or not mgr.is_running:
        return '<div class="alert alert-danger">Not connected</div>'
    flood = request.form.get("flood") == "1"
    mgr.send_advertisement(flood=flood)
    return '<div class="alert alert-success">Advertisement sent</div>'
