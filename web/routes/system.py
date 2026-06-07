import socket
import logging
from flask import Blueprint, jsonify, request
from core import store
from config.settings import POLL_INTERVAL, FLASK_PORT

log = logging.getLogger("PrinterMonitor")

bp = Blueprint("system", __name__)


@bp.route('/api/status')
def api_status():
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        log.exception("Unable to determine host IP")
        host_ip = "127.0.0.1"
    return jsonify({
        "status":        "running",
        "poll_interval": POLL_INTERVAL,  # 🔥 این خط باید باشد
        "host_ip":       host_ip,
        "port":          FLASK_PORT,
        "dashboard_url": f"http://{host_ip}:{FLASK_PORT}/",
        **store.poll_stats,
    })


@bp.route('/api/poll/now', methods=['POST'])
def api_poll_now():
    import threading
    from core.poller import poll_all, _polling_lock

    if _polling_lock.locked():
        log.warning('Manual pull request rejected: poll_all is already running')
        return jsonify({"status": "busy", "error": "Pull already in progress"}), 409

    log.info('Manual pull requested via API')
    try:
        threading.Thread(target=poll_all, daemon=True).start()
        return jsonify({"status": "started"})
    except Exception as e:
        log.exception('Failed to start manual pull')
        return jsonify({"status": "error", "error": str(e)}), 500
