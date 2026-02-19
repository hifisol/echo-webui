from flask import Blueprint, render_template

from core.database import query_db
from tools.system import get_system_info, get_wireless_info

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    return render_template("dashboard.html")


@bp.route("/api/dashboard/stats")
def stats():
    db_path = bp.config["database"]["path"]
    ap_count = query_db(db_path, "SELECT COUNT(*) as c FROM access_points", one=True)
    client_count = query_db(db_path, "SELECT COUNT(*) as c FROM clients", one=True)
    job_count = query_db(db_path, "SELECT COUNT(*) as c FROM jobs WHERE status='running'", one=True)
    handshake_count = query_db(db_path, "SELECT COUNT(*) as c FROM handshakes", one=True)

    sys_info = get_system_info()
    wifi_info = get_wireless_info()

    return render_template(
        "components/_dashboard_stats.html",
        aps=ap_count["c"] if ap_count else 0,
        clients=client_count["c"] if client_count else 0,
        running_jobs=job_count["c"] if job_count else 0,
        handshakes=handshake_count["c"] if handshake_count else 0,
        sys=sys_info,
        wifi=wifi_info,
    )
