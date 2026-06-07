"""
ساخت Flask app و ثبت همه blueprintها
"""

import os
from flask import Flask, jsonify, redirect, request, url_for
from flask_login import current_user
from web.routes.dashboard  import bp as bp_dashboard
from web.routes.printers   import bp as bp_printers
from web.routes.logs       import bp as bp_logs
from web.routes.export_bp  import bp as bp_export
from web.routes.scan       import bp as bp_scan
from web.routes.discover   import bp as bp_discover
from web.routes.stats      import bp as bp_stats
from web.routes.validation import bp as bp_validation
from web.routes.system     import bp as bp_system
from web.routes.users      import bp as bp_users
from web.auth import auth_bp, init_auth, user_can_access_module
from config import settings

# مسیر مطلق پوشه web/ (همین فایل در web/ قرار دارد)
_WEB_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_WEB_DIR, "templates"),
        static_folder=os.path.join(_WEB_DIR, "static"),
    )

    app.config.update(
        SECRET_KEY=settings.SECRET_KEY,
        MAIL_SERVER=settings.MAIL_SERVER,
        MAIL_PORT=settings.MAIL_PORT,
        MAIL_USE_TLS=settings.MAIL_USE_TLS,
        MAIL_USERNAME=settings.MAIL_USERNAME,
        MAIL_PASSWORD=settings.MAIL_PASSWORD,
        GOOGLE_CLIENT_ID=settings.GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET=settings.GOOGLE_CLIENT_SECRET,
        RECAPTCHA_SITE_KEY=settings.RECAPTCHA_SITE_KEY,
        RECAPTCHA_SECRET_KEY=settings.RECAPTCHA_SECRET_KEY,
    )

    init_auth(app)

    for blueprint in (
        auth_bp,
        bp_dashboard, bp_printers, bp_logs, bp_export,
        bp_scan, bp_discover, bp_stats, bp_validation, bp_system, bp_users,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def protect_routes():
        endpoint = request.endpoint or ""
        public_endpoints = {
            "static",
            "auth.login",
            "auth.register",
            "auth.forgot_password",
            "auth.reset_password",
            "auth.google_login",
            "auth.google_callback",
            "system.api_status",
        }
        if endpoint.startswith("static"):
            return None
        if not current_user.is_authenticated:
            if endpoint in public_endpoints:
                return None
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "unauthorized", "login_url": url_for("auth.login", next=request.url)}), 401
            return redirect(url_for("auth.login", next=request.url))

        if not getattr(current_user, "is_verified", False):
            if request.path in ("/", "/auth/logout") or endpoint == "auth.logout":
                return None
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "pending_verification"}), 403
            return redirect(url_for("dashboard.index"))

        endpoint_modules = {
            "printers.api_printers": "printers",
            "printers.api_printer": "printers",
            "printers.debug_printer": "printers",
            "printers.api_add": "printers",
            "printers.api_bulk_add": "printers",
            "printers.api_remove": "printers",
            "printers.api_auto_add_printer": "printers",
            "printers.rename_printer": "printers",
            "logs.api_printer_log": "logs",
            "logs.api_all_logs": "logs",
            "logs.api_clear_logs": "logs",
            "logs.api_manual_event": "logs",
            "export.export_excel": "excel",
            "export.export_logs": "excel",
            "users.users_page": "users",
            "users.api_users": "users",
            "users.api_user_role": "users",
            "users.api_user_verify": "users",
            "users.api_delete_user": "users",
            "users.api_user_add": "users",
            "users.api_user_access": "users",
        }
        module_name = endpoint_modules.get(endpoint)
        if module_name and not user_can_access_module(current_user, module_name):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "forbidden"}), 403
            return redirect(url_for("dashboard.index"))

        role = getattr(current_user, "role", "viewer")
        if role == "admin":
            return None

        viewer_allowed = {
            "dashboard.index",
            "system.api_status",
            "printers.api_printers",
            "printers.api_printer",
            "logs.api_printer_log",
            "logs.api_all_logs",
            "stats.api_daily_stats",
            "auth.logout",
        }
        manager_allowed = viewer_allowed | {"export.export_excel"}

        if role == "manager":
            if endpoint == "export.export_logs":
                if request.args.get("format", "csv").lower() == "excel":
                    return None
            elif endpoint in manager_allowed:
                return None

            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "forbidden"}), 403
            return redirect(url_for("dashboard.index"))

        if endpoint in viewer_allowed:
            return None
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "forbidden"}), 403
        return redirect(url_for("dashboard.index"))

    @app.after_request
    def cors(r):
        r.headers['Access-Control-Allow-Origin']  = '*'
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        r.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE,OPTIONS'
        return r

    return app