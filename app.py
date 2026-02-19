import atexit
import secrets

from flask import Flask, Response, render_template, request, redirect, url_for, session

from core.config import load_config
from core.database import init_db
from core.auth import init_auth, check_rate_limit, record_attempt
from core.events import event_bus
from core.tasks import TaskRunner
from tools.wifi_scanner import WiFiScanner
from tools.interface import InterfaceManager

from blueprints import dashboard, system, jobs, recon, attacks, sdr, mesh


def create_app():
    cfg = load_config()
    app = Flask(__name__)
    app.config["cfg"] = cfg

    # Database
    db_path = cfg["database"]["path"]
    init_db(db_path)

    # Auth
    init_auth(app, cfg["auth"]["token"])

    # Task runner
    runner = TaskRunner(
        db_path=db_path,
        max_workers=cfg["jobs"]["max_concurrent"],
        buffer_lines=cfg["jobs"]["output_buffer_lines"],
    )
    app.config["task_runner"] = runner

    # WiFi scanner
    scanner = WiFiScanner(
        db_path=db_path,
        iface=cfg["interfaces"]["wifi"],
        channels=cfg["scanner"]["default_channels"],
        hop_interval=cfg["scanner"]["channel_hop_interval"],
    )
    app.config["wifi_scanner"] = scanner

    # Interface manager
    app.config["interface_mgr"] = InterfaceManager()

    # MeshCore manager
    mesh_cfg = cfg.get("mesh", {})
    if mesh_cfg.get("enabled", False):
        from tools.mesh_manager import MeshManager
        mesh_mgr = MeshManager(
            db_path=db_path,
            serial_port=mesh_cfg.get("serial_port", "/dev/ttyUSB0"),
            baud_rate=mesh_cfg.get("baud_rate", 115200),
        )
        app.config["mesh_manager"] = mesh_mgr
        if mesh_cfg.get("auto_connect", False):
            mesh_mgr.start()

    # Pass config to dashboard blueprint
    dashboard.bp.config = cfg

    # Register blueprints
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(jobs.bp)
    app.register_blueprint(recon.bp)
    app.register_blueprint(attacks.bp)
    app.register_blueprint(sdr.bp)
    app.register_blueprint(mesh.bp)

    # Login page
    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        if request.method == "POST":
            ip = request.remote_addr
            if not check_rate_limit(ip):
                return render_template("login.html", error="Too many attempts. Try again later.")
            record_attempt(ip)
            token = request.form.get("token", "")
            if secrets.compare_digest(token, cfg["auth"]["token"]):
                session["authenticated"] = True
                session.permanent = True
                return redirect(url_for("dashboard.index"))
            return render_template("login.html", error="Invalid token.")
        return render_template("login.html")

    # Health check
    @app.route("/health")
    def health():
        return "ok"

    # SSE endpoints
    @app.route("/api/events/<channel>")
    def sse_stream(channel):
        allowed = {"scan", "jobs", "system", "sdr", "mesh"}
        if channel not in allowed:
            return "Invalid channel", 404

        def generate():
            for msg in event_bus.subscribe(channel):
                yield msg

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Interface API
    @app.route("/api/interface/status")
    def interface_status():
        from tools.system import get_wireless_info
        return render_template("components/_interface_status.html", wifi=get_wireless_info())

    @app.route("/api/interface/monitor", methods=["POST"])
    def toggle_monitor():
        mgr = app.config["interface_mgr"]
        iface = cfg["interfaces"]["wifi"]
        mode = mgr.get_mode(iface)
        if mode == "monitor":
            mgr.set_managed_mode(iface)
        else:
            mgr.set_monitor_mode(iface)
        from tools.system import get_wireless_info
        return render_template("components/_interface_status.html", wifi=get_wireless_info())

    @app.route("/api/interface/channel", methods=["POST"])
    def set_channel():
        mgr = app.config["interface_mgr"]
        iface = cfg["interfaces"]["wifi"]
        channel = request.form.get("channel", "1")
        try:
            ch = int(channel)
            mgr.set_channel(iface, ch)
        except (ValueError, TypeError):
            pass
        from tools.system import get_wireless_info
        return render_template("components/_interface_status.html", wifi=get_wireless_info())

    # Cleanup on shutdown
    @atexit.register
    def cleanup():
        if scanner.is_running:
            scanner.stop()
        mgr = app.config["interface_mgr"]
        iface = cfg["interfaces"]["wifi"]
        if mgr.is_available(iface):
            mgr.set_managed_mode(iface)
        mesh_mgr = app.config.get("mesh_manager")
        if mesh_mgr and mesh_mgr.is_running:
            mesh_mgr.stop()

    return app


app = create_app()

if __name__ == "__main__":
    cfg = load_config()
    app.run(host=cfg["server"]["host"], port=cfg["server"]["port"], debug=True)
