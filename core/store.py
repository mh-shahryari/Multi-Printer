"""
حالت سراسری برنامه:
- لیست پرینترها (PRINTERS) و قفل آن
- داده‌های لحظه‌ای (printer_data) و قفل آن
- آمار polling
- مدیریت فایل printers.json
- ذخیره مقادیر قبلی شمارنده‌ها در دیتابیس (کلاس PrevStore)
"""

import json
import os
import threading
import logging

from config.settings import PRINTERS_FILE, DEFAULT_PRINTERS
from core.database import load_printer_counters, save_printer_counters

log = logging.getLogger("PrinterMonitor")

# ─── قفل‌ها ──────────────────────────────────────────────────────
printers_lock = threading.Lock()
data_lock = threading.Lock()
_prev_lock = threading.Lock()   # قفل برای PrevStore

# ─── داده سراسری ────────────────────────────────────────────────
printer_data = {}          # ip → dict داده کامل پرینتر
poll_stats = {"count": 0, "last": None, "errors": 0}


# ─── کلاس ذخیره مقادیر قبلی با پشتیبان دیتابیس ────────────────────
class PrevStore:
    """
    ذخیره‌سازی مقادیر قبلی شمارنده‌ها در حافظه (کش) و دیتابیس.
    
    🔥 تغییر مهم: اگر در دیتابیس رکوردی وجود نداشته باشد، get() مقدار None برمی‌گرداند
    (نه دیکشنری خالی) تا بتوان اولین poll را تشخیص داد.
    """

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, ip: str):
        """
        دریافت مقادیر قبلی برای یک پرینتر.
        🔥 اگر هیچ داده قبلی در دیتابیس یا کش وجود نداشته باشد، None برمی‌گرداند.
        """
        with self._lock:
            # اگر در کش هست، برگردان
            if ip in self._cache:
                return self._cache[ip].copy() if self._cache[ip] else None
            
            # از دیتابیس بخوان
            db_data = load_printer_counters(ip)
            
            if db_data is None:
                # هیچ داده‌ای در دیتابیس وجود ندارد
                self._cache[ip] = None
                return None
            
            # داده در دیتابیس وجود دارد
            self._cache[ip] = db_data
            return db_data.copy()

    def set(self, ip: str, data: dict):
        """ذخیره مقادیر جدید برای یک پرینتر (در کش و دیتابیس)."""
        with self._lock:
            existing = self._cache.get(ip) or load_printer_counters(ip) or {}
            normalized = {
                "toner_level": existing.get("toner_level"),
                "last_alert_codes": existing.get("last_alert_codes", []),
                "manual_override": existing.get("manual_override", 0),
                "override_color": existing.get("override_color"),
                "override_base_level": existing.get("override_base_level"),
                "override_start_total": existing.get("override_start_total"),
                "override_start_toner": existing.get("override_start_toner"),
                "yield_per_page": existing.get("yield_per_page", 2000),
                **existing,
                **data
            }
            self._cache[ip] = normalized.copy()
            save_printer_counters(ip, normalized)
            log.debug(f"PrevStore.set: {ip} -> total={normalized.get('print_total')} toner={normalized.get('toner_level')} last_alerts={normalized.get('last_alert_codes')}")

    def delete(self, ip: str):
        """حذف مقادیر یک پرینتر (در صورت حذف پرینتر)."""
        with self._lock:
            self._cache.pop(ip, None)
            # در دیتابیس هم می‌توان حذف کرد، ولی فعلاً نیازی نیست

    def is_initialized(self, ip: str) -> bool:
        """بررسی می‌کند آیا قبلاً این پرینتر مقداردهی شده است."""
        with self._lock:
            if ip in self._cache:
                return self._cache[ip] is not None
            db_data = load_printer_counters(ip)
            return db_data is not None


# ─── نمونه سراسری PrevStore ──────────────────────────────────────
_prev = PrevStore()

# ─── فیلدهای مجاز در printers.json ─────────────────────────────
_PRINTER_ALLOWED_FIELDS = {"ip", "name", "community", "brand", "nickname", "device_type"}


def _normalize_printer(p: dict) -> dict:
    return {
        "ip": str(p.get("ip", "")).strip(),
        "name": str(p.get("name", "")).strip() or str(p.get("ip", "")),
        "community": str(p.get("community", "public")).strip() or "public",
        "nickname": str(p.get("nickname", "")).strip(),
        "device_type": str(p.get("device_type", "")).strip() or "unknown",
        **({"brand": str(p["brand"]).strip().lower()}
           if p.get("brand") and p.get("brand") not in ("", "unknown") else {}),
    }


def _deduplicate_printers(printers: list) -> list:
    seen = set()
    result = []
    for p in printers:
        ip = str(p.get("ip", "")).strip()
        if ip and ip not in seen:
            seen.add(ip)
            result.append(p)
    return result


def load_printers() -> list:
    if os.path.exists(PRINTERS_FILE):
        try:
            with open(PRINTERS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            normalized = _deduplicate_printers([_normalize_printer(p) for p in data])
            if normalized:
                return normalized
        except Exception as e:
            log.exception("printers.json خواندن ناموفق: %s", e)
    return [_normalize_printer(p) for p in DEFAULT_PRINTERS]


def save_printers(printers: list) -> list:
    clean = _deduplicate_printers([_normalize_printer(p) for p in printers])
    with open(PRINTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


# ─── لیست اولیه ──────────────────────────────────────────────────
PRINTERS: list = load_printers()