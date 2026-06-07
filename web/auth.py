"""Authentication blueprint for login, registration, reset, and Google OAuth."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps
import json
import re

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_login import LoginManager

from config import settings
from models import User
from utils import generate_reset_token, hash_token, send_email, verify_recaptcha, verify_reset_token

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()
oauth = OAuth()


def _api_unauthorized():
    login_url = url_for("auth.login", next=request.url)
    if request.path.startswith("/api/") or request.is_json or "application/json" in request.headers.get("Accept", ""):
        return jsonify({"error": "unauthorized", "login_url": login_url}), 401
    return redirect(login_url)


def init_auth(app):
    app.config.setdefault("SECRET_KEY", settings.SECRET_KEY)
    app.config.setdefault("MAIL_SERVER", settings.MAIL_SERVER)
    app.config.setdefault("MAIL_PORT", settings.MAIL_PORT)
    app.config.setdefault("MAIL_USE_TLS", settings.MAIL_USE_TLS)
    app.config.setdefault("MAIL_USERNAME", settings.MAIL_USERNAME)
    app.config.setdefault("MAIL_PASSWORD", settings.MAIL_PASSWORD)
    app.config.setdefault("GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID)
    app.config.setdefault("GOOGLE_CLIENT_SECRET", settings.GOOGLE_CLIENT_SECRET)
    app.config.setdefault("RECAPTCHA_SITE_KEY", settings.RECAPTCHA_SITE_KEY)
    app.config.setdefault("RECAPTCHA_SECRET_KEY", settings.RECAPTCHA_SECRET_KEY)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "برای ادامه وارد شوید"
    login_manager.login_message_category = "warning"

    @login_manager.unauthorized_handler
    def unauthorized():
        return _api_unauthorized()

    oauth.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


def _next_url(default_endpoint="dashboard.index"):
    next_url = request.values.get("next")
    if next_url and next_url.startswith("/"):
        return next_url
    return url_for(default_endpoint)


def has_role(user, *roles):
    return bool(user and getattr(user, "role", None) in roles)


def _clean_list(value):
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return [value]
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    items = []
    for item in value:
        text = str(item).strip()
        if text and text not in items:
            items.append(text)
    return items


def office_for_ip(ip: str) -> str:
    ip = (ip or "").strip()
    if not ip:
        return "other"
    for office_id, subnet in settings.OFFICE_SUBNETS.items():
        if subnet and ip.startswith(f"{subnet}."):
            return office_id
    return "other"


def user_allowed_offices(user):
    return _clean_list(getattr(user, "allowed_offices", []))


def user_allowed_modules(user):
    return _clean_list(getattr(user, "allowed_modules", []))


def user_can_access_module(user, module_name: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == "admin":
        return True
    allowed = user_allowed_modules(user)
    return not allowed or module_name in allowed


def user_can_access_office(user, ip: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == "admin":
        return True
    allowed = user_allowed_offices(user)
    if not allowed:
        return True
    office_id = office_for_ip(ip)
    return office_id in allowed


def allowed_printer_ips(user):
    if not user or not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "role", None) == "admin":
        return []
    allowed = user_allowed_offices(user)
    if not allowed:
        return []
    from core import store

    with store.printers_lock:
        printers = list(store.PRINTERS)
    allowed_ips = []
    for printer in printers:
        office_id = office_for_ip(printer.get("ip", ""))
        if office_id in allowed:
            allowed_ips.append(printer.get("ip"))
    return [ip for ip in allowed_ips if ip]


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not has_role(current_user, *roles):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(view):
    return role_required("admin")(view)


def _unique_username(base_name: str) -> str:
    cleaned = "".join(ch for ch in base_name.lower() if ch.isalnum()) or "user"
    candidate = cleaned
    suffix = 1
    while User.find_by_identifier(candidate):
        candidate = f"{cleaned}{suffix}"
        suffix += 1
    return candidate


USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        if not verify_recaptcha(request.form.get("g-recaptcha-response", ""), request.remote_addr):
            error = "کپچا معتبر نیست"
        else:
            identifier = (request.form.get("identifier") or "").strip()
            password = request.form.get("password") or ""
            user = User.find_by_identifier(identifier)
            if user and user.is_active and user.verify_password(password):
                login_user(user, remember=bool(request.form.get("remember")))
                user.touch_login()
                flash("با موفقیت وارد شدید", "success")
                return redirect(url_for("dashboard.index"))
            error = "نام کاربری/ایمیل یا رمز عبور اشتباه است"

    return render_template(
        "login.html",
        error=error,
        google_enabled=bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET")),
        recaptcha_site_key=current_app.config.get("RECAPTCHA_SITE_KEY", ""),
        load_dashboard_scripts=False,
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        if not verify_recaptcha(request.form.get("g-recaptcha-response", ""), request.remote_addr):
            error = "کپچا معتبر نیست"
        else:
            username = (request.form.get("username") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm_password") or ""

            if not username or not email or not password:
                error = "همه فیلدها الزامی هستند"
            elif not USERNAME_RE.fullmatch(username):
                error = "نام کاربری فقط باید با حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد"
            elif password != confirm:
                error = "رمز عبور و تکرار آن یکسان نیست"
            elif User.find_by_identifier(username):
                error = "نام کاربری قبلاً استفاده شده است"
            elif User.find_by_email(email):
                error = "ایمیل قبلاً ثبت شده است"
            else:
                user = User.create(username=username, email=email, password=password, is_verified=False)
                if user:
                    login_user(user)
                    user.touch_login()
                    if user.is_verified:
                        flash("ثبت‌نام انجام شد و حساب شما فعال است.", "success")
                    else:
                        flash("ثبت‌نام انجام شد. حساب شما در انتظار تأیید است.", "warning")
                    return redirect(url_for("dashboard.index"))
                error = "امکان ایجاد حساب وجود نداشت"

    return render_template(
        "register.html",
        error=error,
        recaptcha_site_key=current_app.config.get("RECAPTCHA_SITE_KEY", ""),
        load_dashboard_scripts=False,
    )


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.find_by_email(email)
        if user:
            token = generate_reset_token(user.id, user.email)
            token_hash = hash_token(token)
            expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
            user.set_reset_token(token_hash, expires_at)
            reset_link = url_for("auth.reset_password", token=token, _external=True)
            text_body = (
                f"برای بازنشانی رمز عبور روی لینک زیر کلیک کنید:\n{reset_link}\n\n"
                "این لینک فقط یک‌بار و تا ۱ ساعت معتبر است."
            )
            html_body = f"<p>برای بازنشانی رمز عبور روی لینک زیر کلیک کنید:</p><p><a href='{reset_link}'>{reset_link}</a></p><p>این لینک فقط یک‌بار و تا ۱ ساعت معتبر است.</p>"
            send_email("بازنشانی رمز عبور", user.email, text_body, html_body)
        message = "اگر ایمیل در سیستم موجود باشد، لینک بازنشانی ارسال می‌شود."

    return render_template(
        "forgot_password.html",
        message=message,
        load_dashboard_scripts=False,
    )


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    payload = verify_reset_token(token)
    token_hash = hash_token(token)
    user = User.find_by_reset_token_hash(token_hash)
    error = None

    if not payload or not user:
        error = "لینک بازنشانی نامعتبر یا منقضی شده است"
    else:
        expires_at = user.reset_token_expires
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now():
                    error = "لینک بازنشانی منقضی شده است"
            except Exception:
                error = "لینک بازنشانی نامعتبر است"

    if request.method == "POST" and not error:
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not password:
            error = "رمز عبور الزامی است"
        elif password != confirm:
            error = "رمز عبور و تکرار آن یکسان نیست"
        else:
            if user.set_password(password):
                user.clear_reset_token()
                flash("رمز عبور با موفقیت تغییر کرد", "success")
                return redirect(url_for("auth.login"))
            error = "امکان تغییر رمز وجود نداشت"

    return render_template(
        "reset_password.html",
        token=token,
        error=error,
        load_dashboard_scripts=False,
    )


@auth_bp.route("/auth/google")
def google_login():
    if not hasattr(oauth, "google"):
        flash("ورود با گوگل فعال نشده است", "error")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    if not hasattr(oauth, "google"):
        flash("ورود با گوگل فعال نشده است", "error")
        return redirect(url_for("auth.login"))
    token = oauth.google.authorize_access_token()
    profile = oauth.google.parse_id_token(token) or {}
    email = (profile.get("email") or "").strip().lower()
    google_id = str(profile.get("sub") or profile.get("id") or "").strip()
    name = (profile.get("name") or profile.get("given_name") or email.split("@")[0] or "user").strip()

    if not email:
        flash("اطلاعات ایمیل از گوگل دریافت نشد", "error")
        return redirect(url_for("auth.login"))

    user = User.find_by_google_id(google_id) if google_id else None
    if not user:
        user = User.find_by_email(email)
    if not user:
        user = User.create(username=_unique_username(name), email=email, google_id=google_id, is_verified=False)
    elif google_id and not user.google_id:
        user.set_google_id(google_id)

    if user:
        login_user(user)
        user.touch_login()
        if user.is_verified:
            flash("با حساب گوگل وارد شدید", "success")
        else:
            flash("حساب شما با گوگل وارد شد اما هنوز در انتظار تأیید ادمین است", "warning")
        return redirect(url_for("dashboard.index"))

    flash("ورود گوگلی انجام نشد", "error")
    return redirect(url_for("auth.login"))




@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("خروج با موفقیت انجام شد", "success")
    return redirect(url_for("auth.login"))
