# config/settings.py

"""
تنظیمات سراسری برنامه
"""

import os

# ─── فایل‌ها و مسیرها ───────────────────────────────────────────
PRINTERS_FILE        = "printers.json"
DB_PATH              = "logs.db"
OID_PROFILES_FILE    = "oid_profiles.json"
VALIDATION_LOG_FILE  = "oid_validation_errors.txt"

# ─── پرینترهای پیش‌فرض ─────────────────────────────────────────
DEFAULT_PRINTERS = [
    {"ip": "172.16.25.53", "name": "Toshiba #1", "community": "public"},
    {"ip": "172.16.25.54", "name": "Toshiba #2", "community": "public"},
    {"ip": "172.16.25.55", "name": "Toshiba #3", "community": "public"},
    {"ip": "172.16.25.57", "name": "Toshiba #4", "community": "public"},
]

# ─── SNMP ───────────────────────────────────────────────────────
SNMP_PORT     = 161

# ─── Polling ────────────────────────────────────────────────────
# 🔥 تغییر: از 30 ثانیه به 60 ثانیه (1 دقیقه)
POLL_INTERVAL = 60   # ثانیه (1 دقیقه)

# ─── Flask ──────────────────────────────────────────────────────
FLASK_PORT = 5053
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")
MAIL_SERVER = os.getenv("MAIL_SERVER", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")

# ─── دفاتر و subnetهای مجاز ─────────────────────────────────────
OFFICE_SUBNETS = {
    "imamat": "172.16.25",
    "soroush": "172.16.24",
    "falestin": "172.16.0",
    "elahiye": "172.16.32",
    "other": None,
}

# ─── Thresholds for toner alerts (percent)
TONER_ALERT_THRESHOLDS = {
    "critical": 5,   # زیر ۵٪ بحرانی
    "warning": 15,   # زیر ۱۵٪ هشدار
    "info": 30,      # زیر ۳۰٪ اطلاع‌رسانی (اختیاری)
}