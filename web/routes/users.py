import logging
import secrets
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user

from models import User
from web.auth import admin_required
from utils import generate_reset_token, hash_token, send_email

bp = Blueprint("users", __name__)
log = logging.getLogger("PrinterMonitor")

ALLOWED_OFFICES = {"imamat", "soroush", "falestin", "elahiye", "other"}
ALLOWED_MODULES = {"printers", "logs", "excel", "users"}

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _validate_username(username: str):
    if not username:
        return "username الزامی است"
    if not USERNAME_RE.fullmatch(username):
        return "نام کاربری فقط باید با حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد"
    return None


def _normalize_selection(values, allowed_values):
    normalized = []
    for value in values or []:
        text = str(value).strip().lower()
        if text in allowed_values and text not in normalized:
            normalized.append(text)
    return normalized


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_verified": bool(user.is_verified),
        "is_active": bool(user.is_active),
        "allowed_offices": list(getattr(user, "allowed_offices", []) or []),
        "allowed_modules": list(getattr(user, "allowed_modules", []) or []),
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@bp.route("/users")
@admin_required
def users_page():
    return render_template("users.html", load_dashboard_scripts=False)


@bp.route("/api/users", methods=["GET"])
@admin_required
def api_users():
    users = [u for u in User.all() if u]
    return jsonify({"users": [_serialize_user(u) for u in users], "total": len(users)})


@bp.route("/api/users", methods=["POST"])
@admin_required
def api_user_add():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "viewer").strip().lower()
    allowed_offices = data.get("allowed_offices") or []
    allowed_modules = data.get("allowed_modules") or []
    allowed_offices = _normalize_selection(allowed_offices, ALLOWED_OFFICES)
    allowed_modules = _normalize_selection(allowed_modules, ALLOWED_MODULES)

    username_error = _validate_username(username)
    if username_error:
        return jsonify({"error": username_error}), 400
    if not email:
        return jsonify({"error": "email الزامی است"}), 400
    if role not in ("admin", "manager", "viewer"):
        return jsonify({"error": "role نامعتبر است"}), 400
    if User.find_by_identifier(username):
        return jsonify({"error": "نام کاربری تکراری است"}), 400
    if User.find_by_email(email):
        return jsonify({"error": "ایمیل تکراری است"}), 400

    temp_password = secrets.token_urlsafe(12)
    user = User.create(
        username=username,
        email=email,
        password=temp_password,
        role=role,
        is_verified=True,
        allowed_offices=allowed_offices,
        allowed_modules=allowed_modules,
    )
    if not user:
        return jsonify({"error": "unable to create user"}), 500

    token = generate_reset_token(user.id, user.email)
    token_hash = hash_token(token)
    expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
    user.set_reset_token(token_hash, expires_at)
    reset_link = url_for("auth.reset_password", token=token, _external=True)
    text_body = (
        f"یک حساب کاربری برای شما ایجاد شده است.\n"
        f"نام کاربری: {username}\n"
        f"برای تنظیم رمز عبور روی لینک زیر کلیک کنید:\n{reset_link}\n\n"
        "این لینک فقط یک‌بار و تا ۱ ساعت معتبر است."
    )
    html_body = (
        f"<p>یک حساب کاربری برای شما ایجاد شده است.</p>"
        f"<p>نام کاربری: <strong>{username}</strong></p>"
        f"<p><a href='{reset_link}'>تنظیم رمز عبور</a></p>"
        f"<p>این لینک فقط یک‌بار و تا ۱ ساعت معتبر است.</p>"
    )
    email_sent = send_email("تنظیم رمز عبور اولیه", user.email, text_body, html_body)
    payload = _serialize_user(user)
    payload["email_sent"] = email_sent
    return jsonify({"status": "ok", "user": payload})


@bp.route("/api/users/<int:user_id>/role", methods=["POST"])
@admin_required
def api_user_role(user_id):
    data = request.get_json() or {}
    role = (data.get("role") or "").strip().lower()
    if role not in ("admin", "manager", "viewer"):
        return jsonify({"error": "role نامعتبر است"}), 400

    target = User.get(user_id)
    if not target:
        return jsonify({"error": "user not found"}), 404

    if target.role == "admin" and role != "admin":
        admins = [u for u in User.all() if u and u.role == "admin"]
        if len(admins) <= 1:
            return jsonify({"error": "حداقل یک admin باید باقی بماند"}), 400

    if target.set_role(role):
        if role == "admin":
            target.set_verified(True)
        return jsonify({"status": "ok", "user": _serialize_user(target)})
    return jsonify({"error": "unable to update role"}), 500


@bp.route("/api/users/<int:user_id>/verify", methods=["POST"])
@admin_required
def api_user_verify(user_id):
    data = request.get_json(silent=True) or {}
    target = User.get(user_id)
    if not target:
        return jsonify({"error": "user not found"}), 404

    verified = data.get("is_verified")
    if verified is None:
        verified = not target.is_verified
    verified = bool(verified)

    if target.role == "admin" and not verified:
        admins = [u for u in User.all() if u and u.role == "admin"]
        if len(admins) <= 1:
            return jsonify({"error": "حداقل یک admin باید تأیید شده بماند"}), 400

    if target.set_verified(verified):
        return jsonify({"status": "ok", "user": _serialize_user(target)})
    return jsonify({"error": "unable to update verification"}), 500


@bp.route("/api/users/<int:user_id>/access", methods=["POST"])
@admin_required
def api_user_access(user_id):
    data = request.get_json(silent=True) or {}
    target = User.get(user_id)
    if not target:
        return jsonify({"error": "user not found"}), 404

    allowed_offices = data.get("allowed_offices") or []
    allowed_modules = data.get("allowed_modules") or []
    allowed_offices = _normalize_selection(allowed_offices, ALLOWED_OFFICES)
    allowed_modules = _normalize_selection(allowed_modules, ALLOWED_MODULES)
    if target.set_access(allowed_offices=allowed_offices, allowed_modules=allowed_modules):
        return jsonify({"status": "ok", "user": _serialize_user(target)})
    return jsonify({"error": "unable to update access"}), 500


@bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def api_delete_user(user_id):
    target = User.get(user_id)
    if not target:
        return jsonify({"error": "user not found"}), 404

    if int(target.id) == int(current_user.id):
        return jsonify({"error": "cannot delete current user"}), 400

    if target.role == "admin":
        admins = [u for u in User.all() if u and u.role == "admin"]
        if len(admins) <= 1:
            return jsonify({"error": "حداقل یک admin باید باقی بماند"}), 400

    if target.delete():
        return jsonify({"status": "deleted", "user_id": user_id})
    return jsonify({"error": "unable to delete user"}), 500
