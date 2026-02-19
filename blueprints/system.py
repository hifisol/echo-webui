from flask import Blueprint, render_template

from tools.system import (
    get_system_info,
    get_usb_devices,
    get_network_interfaces,
    get_wireless_info,
)

bp = Blueprint("system", __name__, url_prefix="/system")


@bp.route("/")
def index():
    return render_template(
        "system/status.html",
        sys=get_system_info(),
        usb=get_usb_devices(),
        interfaces=get_network_interfaces(),
        wifi=get_wireless_info(),
    )


@bp.route("/api/metrics")
def metrics():
    return render_template(
        "system/_sysinfo.html",
        sys=get_system_info(),
        usb=get_usb_devices(),
        interfaces=get_network_interfaces(),
        wifi=get_wireless_info(),
    )
