# core/enhanced_collector.py

"""
جمع‌آوری پیشرفته داده‌ها با استفاده از روش‌های test_toner.py:
- Walk کامل جدول prtMarkerSuppliesTable
- Walk جدول prtInputTable (سینی‌ها)
- OIDهای جایگزین برای HP, Canon, Brother
- تشخیص خودکار نسخه SNMP
- ذخیره اطلاعات دقیق تونر در دیتابیس
- ثبت لاگ در toner_report.txt
"""

import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from config.settings import DB_PATH, VALIDATION_LOG_FILE
from core.snmp.protocol import snmp_get_with_fallback, snmp_get, _SNMP_VERSION_CACHE
from core import store
from core.collectors.base import _counters_event, apply_toner_override
from core.database import add_event

log = logging.getLogger("PrinterMonitor")

import json
import os

# ─── تنظیمات ─────────────────────────────────────────────────────
ENHANCED_TIMEOUT = 3.0   # timeout برای هر OID
ENHANCED_MAX_SUPPLIES = 15  # حداکثر تعداد مواد مصرفی برای walk
DEFAULT_CARTRIDGE_YIELD = 2000  # صفحات تقریبی برای برآورد تونر هنگامی که سنسور در دسترس نیست

# OIDهای جایگزین برای HP
HP_ALTERNATE_OIDS = {
    "CE505A": ["1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1"],
    "CF283A": ["1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1"],
    "CF287A": ["1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1"],
    "W9008MC": ["1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1"],
    "CC388A": ["1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1"],
}

# OIDهای جایگزین برای Canon
CANON_ALTERNATE_OIDS = [
    "1.3.6.1.4.1.1602.1.2.1.1.1.1.1",
    "1.3.6.1.4.1.1602.1.2.1.1.1.2.1",
]

# OID تونر Brother
BROTHER_TONER_OID = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.1.1"
BROTHER_DRUM_OID = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.1.2"


# ─── توابع کمکی ───────────────────────────────────────────────────
def _log_to_toner_report(content: str):
    """اضافه کردن خط به فایل toner_report.txt"""
    try:
        with open("toner_report.txt", "a", encoding="utf-8") as f:
            f.write(content + "\n")
    except Exception as e:
        log.error(f"خطا در نوشتن toner_report: {e}")


def _log_validation_error(ip: str, error_type: str, details: str):
    """ثبت خطا در فایل validation log"""
    try:
        timestamp = datetime.now().isoformat()
        with open(VALIDATION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] IP: {ip} | Type: enhanced_{error_type}\n")
            f.write(f"  Details: {details}\n\n")
    except Exception as e:
        log.error(f"خطا در نوشتن validation log: {e}")


def detect_snmp_version(ip: str, community: str = "public", timeout: float = 2.0) -> Optional[int]:
    """
    تشخیص نسخه SNMP با تست sysDescr
    بازگشت: 1, 2, یا None
    """
    cache_key = f"{ip}_{community}"
    if cache_key in _SNMP_VERSION_CACHE:
        return _SNMP_VERSION_CACHE[cache_key]

    oid = "1.3.6.1.2.1.1.1.0"
    
    # تست v2c اول
    try:
        result = snmp_get(ip, oid, community, timeout=timeout, version=2)
        if result is not None and str(result).strip():
            _SNMP_VERSION_CACHE[cache_key] = 2
            return 2
    except:
        pass
    
    # تست v1
    try:
        result = snmp_get(ip, oid, community, timeout=timeout, version=1)
        if result is not None and str(result).strip():
            _SNMP_VERSION_CACHE[cache_key] = 1
            return 1
    except:
        pass
    
    _SNMP_VERSION_CACHE[cache_key] = None
    return None


def try_alternative_oids(ip: str, community: str, brand: str, cartridge_model: str = "", 
                         snmp_version: int = None, timeout: float = 3.0) -> Optional[int]:
    """تلاش با OIDهای جایگزین برای دریافت سطح تونر"""
    
    if brand == "hp":
        # اول OIDهای مخصوص مدل کارتریج
        for model_key, oid_list in HP_ALTERNATE_OIDS.items():
            if model_key in cartridge_model:
                for oid in oid_list:
                    val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=timeout)
                    if val is not None:
                        try:
                            int_val = int(val)
                            if 0 <= int_val <= 100:
                                return int_val
                        except:
                            pass
        
        # OIDهای عمومی HP
        general_oids = [
            "1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.1.5.5.1.1",
            "1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1",
            "1.3.6.1.4.1.11.2.3.9.1.1.7.0",
        ]
        for oid in general_oids:
            val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=timeout)
            if val is not None:
                try:
                    int_val = int(val)
                    if 0 <= int_val <= 100:
                        return int_val
                except:
                    pass
    
    elif brand == "canon":
        for oid in CANON_ALTERNATE_OIDS:
            val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=timeout)
            if val is not None:
                try:
                    int_val = int(val)
                    if 0 <= int_val <= 100:
                        return int_val
                except:
                    pass
    
    return None


def walk_supplies_table(ip: str, community: str, brand: str = "unknown", 
                        snmp_version: int = None, timeout: float = 2.0, current_total: int = None) -> List[Dict]:
    """
    Walk کامل روی جدول prtMarkerSuppliesTable
    بازگشت: لیستی از دیکشنری‌های حاوی اطلاعات کارتریج‌ها
    """
    supplies = []
    
    # برای Brother، روش اختصاصی
    if brand == "brother":
        toner_level = snmp_get_with_fallback(ip, BROTHER_TONER_OID, community, 
                                              version=snmp_version, timeout=timeout)
        if toner_level is not None:
            try:
                level = int(toner_level)
                if 0 <= level <= 100:
                    supplies.append({
                        "index": 1,
                        "name": "Black Toner",
                        "model": "Toner Cartridge",
                        "type": 3,
                        "type_name": "toner",
                        "unit": "percent",
                        "max": 100,
                        "remaining": level,
                        "percent": level,
                        "status": "critical" if level <= 10 else "low" if level <= 25 else "ok",
                    })
            except:
                pass
        
        # درام هم بخوانیم
        drum_level = snmp_get_with_fallback(ip, BROTHER_DRUM_OID, community,
                                             version=snmp_version, timeout=timeout)
        if drum_level is not None:
            try:
                level = int(drum_level)
                if 0 <= level <= 100:
                    supplies.append({
                        "index": 2,
                        "name": "Drum Unit",
                        "model": "Drum Unit",
                        "type": 7,  # OPC type
                        "type_name": "opc",
                        "unit": "percent",
                        "max": 100,
                        "remaining": level,
                        "percent": level,
                        "status": "critical" if level <= 10 else "low" if level <= 25 else "ok",
                    })
            except:
                pass
        
        return supplies
    
    # روش استاندارد برای سایر برندها
    for idx in range(1, ENHANCED_MAX_SUPPLIES + 1):
        try:
            name_oid = f"1.3.6.1.2.1.43.11.1.1.6.1.{idx}"
            name = snmp_get_with_fallback(ip, name_oid, community, 
                                          version=snmp_version, timeout=timeout)
            
            if name is None:
                if idx >= 5 and brand in ["canon", "hp", "brother"]:
                    break
                continue
            
            name_str = str(name).strip()
            
            type_oid = f"1.3.6.1.2.1.43.11.1.1.5.1.{idx}"
            stype = snmp_get_with_fallback(ip, type_oid, community,
                                           version=snmp_version, timeout=timeout)
            
            max_oid = f"1.3.6.1.2.1.43.11.1.1.8.1.{idx}"
            max_val = snmp_get_with_fallback(ip, max_oid, community,
                                             version=snmp_version, timeout=timeout)
            
            rem_oid = f"1.3.6.1.2.1.43.11.1.1.9.1.{idx}"
            rem_val = snmp_get_with_fallback(ip, rem_oid, community,
                                             version=snmp_version, timeout=timeout)
            
            stype_int = 0
            if stype is not None and str(stype).lstrip('-').isdigit():
                stype_int = int(stype)
            
            type_names = {
                1: "other", 2: "unknown", 3: "toner", 4: "wasteToner",
                5: "ink", 6: "wasteInk", 7: "OPC", 8: "developer",
                9: "fuser", 10: "cleaner", 11: "transfer", 12: "staples",
                21: "cartridge"
            }
            type_name = type_names.get(stype_int, f"type_{stype_int}")
            
            percent = None
            max_int = -2
            rem_int = -2
            
            try:
                if max_val is not None and str(max_val).lstrip('-').isdigit():
                    max_int = int(max_val)
                if rem_val is not None and str(rem_val).lstrip('-').isdigit():
                    rem_int = int(rem_val)
                
                if max_int > 0 and rem_int >= 0:
                    percent = round(rem_int / max_int * 100)
                elif rem_int >= 0 and rem_int <= 100:
                    percent = rem_int
                    max_int = 100
            except:
                pass
            
            # اگر درصد نداریم، OIDهای جایگزین را امتحان کن
            if percent is None and brand in ["hp", "canon"]:
                alt_percent = try_alternative_oids(ip, community, brand, name_str, snmp_version, timeout)
                if alt_percent is not None:
                    percent = alt_percent
                    rem_int = alt_percent
                    max_int = 100

            # اگر هنوز درصد نداریم اما سنسور گزارش نمی‌کند (rem_int == -2)،
            # تلاش برای برآورد مبتنی بر دلتا شمارنده کل چاپ (اگر موجود باشد).
            if percent is None and rem_int == -2 and current_total is not None:
                try:
                    prev = store._prev.get(ip) or {}
                    prev_total = prev.get("print_total") if prev else None
                    yield_pages = prev.get("yield_per_page", DEFAULT_CARTRIDGE_YIELD)
                    if prev_total is not None and isinstance(prev_total, int) and current_total >= prev_total:
                        pages_used = current_total - prev_total
                    else:
                        # اگر مقدار قبلی نداریم، برآورد محافظه‌کارانه با استفاده از modulo از total
                        try:
                            pages_used = current_total % yield_pages
                        except Exception:
                            pages_used = 0
                    est_remaining = max(0, yield_pages - pages_used)
                    percent = round(est_remaining / yield_pages * 100)
                    rem_int = est_remaining
                    max_int = yield_pages
                except Exception:
                    pass
            
            # وضعیت
            status = "N/A"
            if percent is not None:
                if percent == 0: status = "empty"
                elif percent <= 10: status = "critical"
                elif percent <= 25: status = "low"
                else: status = "ok"
            elif rem_int == -2:
                # بررسی: آیا OID بدون سنسور است یا اصلاً موجود نیست؟
                # برای HP و Canon: اگر نام کارتریج موجود است، شاید سنسور باشد
                # برای branded devices که نام دارند اما rem -2، بیشتر "not_reported" است
                status = "no_sensor" if name_str and name_str != "Unknown" else "not_supported"
            elif rem_int == -3:
                status = "not_supported"
            elif rem_int > 0 and max_int == -2:
                if rem_int <= 100:
                    percent = rem_int
                    status = "ok" if percent > 25 else "low" if percent > 10 else "critical"
            
            # فیلتر Unknownهای تکراری
            if name_str.startswith("Unknown"):
                unknown_count = sum(1 for s in supplies if s["name"].startswith("Unknown"))
                if unknown_count > 2:
                    continue
            
            supplies.append({
                "index": idx,
                "name": name_str,
                "model": name_str,
                "type": stype_int,
                "type_name": type_name,
                "unit": "unknown",
                "max": max_int if max_int != -2 else (100 if percent is not None else "N/A"),
                "remaining": rem_int if rem_int >= 0 else ("N/A" if rem_int == -2 else "unsupported"),
                "percent": percent,
                "status": status,
            })
            
        except Exception as e:
            if idx <= 3:
                _log_validation_error(ip, "walk_supplies_exception", f"idx={idx}: {e}")
    
    return supplies


def walk_input_trays(ip: str, community: str, snmp_version: int = None, timeout: float = 2.0) -> List[Dict]:
    """Walk روی جدول prtInputTable برای سینی‌ها"""
    trays = []
    
    for idx in range(1, 8):
        try:
            name_oid = f"1.3.6.1.2.1.43.8.2.1.13.1.{idx}"
            name = snmp_get_with_fallback(ip, name_oid, community, 
                                          version=snmp_version, timeout=timeout)
            
            cap_oid = f"1.3.6.1.2.1.43.8.2.1.9.1.{idx}"
            cap_val = snmp_get_with_fallback(ip, cap_oid, community,
                                             version=snmp_version, timeout=timeout)
            
            level_oid = f"1.3.6.1.2.1.43.8.2.1.10.1.{idx}"
            level_val = snmp_get_with_fallback(ip, level_oid, community,
                                               version=snmp_version, timeout=timeout)
            
            if name is None and cap_val is None and level_val is None:
                continue
            
            name_str = str(name).strip() if name else f"Tray {idx}"
            
            try:
                cap_int = int(cap_val) if cap_val is not None and str(cap_val).lstrip('-').isdigit() else 0
            except:
                cap_int = 0
            
            try:
                if level_val is not None and str(level_val).lstrip('-').isdigit():
                    level_int = int(level_val)
                else:
                    level_int = -2
            except:
                level_int = -2
            
            fill_percent = None
            status = "unknown"
            
            if level_int == -2:
                status = "no_sensor"
            elif level_int == -3:
                status = "not_supported"
            elif cap_int > 0 and level_int >= 0:
                fill_percent = round(level_int / cap_int * 100)
                if level_int == 0:
                    status = "empty"
                elif fill_percent <= 25:
                    status = "low"
                elif fill_percent <= 75:
                    status = "medium"
                else:
                    status = "ok"
            elif level_int >= 0 and level_int <= 100 and cap_int == 0:
                fill_percent = level_int
                status = "ok" if level_int > 25 else "low" if level_int > 10 else "critical"
            
            trays.append({
                "index": idx,
                "name": name_str,
                "capacity": cap_int,
                "level": level_int if level_int >= 0 else ("N/A" if level_int == -2 else "unsupported"),
                "fill_percent": fill_percent,
                "status": status,
            })
            
        except Exception as e:
            continue
    
    return trays


def _save_oid_profile(ip: str, community: str, snmp_version: int, model: str,
                      device_type: str, total: int, color: Optional[int], bw: int,
                      supplies: List[Dict], trays: List[Dict], scan_ms: int):
    """پروفایل OID را برای یک IP بسازد و در oid_profiles.json ذخیره کند."""
    try:
        candidates = {
            "sys_descr": "1.3.6.1.2.1.1.1.0",
            "sys_uptime": "1.3.6.1.2.1.1.3.0",
            "sys_hostname": "1.3.6.1.2.1.1.5.0",
        }
        oids = {}
        active = 0
        rejected = {}
        for key, oid in candidates.items():
            try:
                val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
                if val is not None:
                    oids[key] = {
                        "oid": oid,
                        "type": "int" if isinstance(val, int) else "str",
                        "category": "sys",
                        "description": key,
                        "unit": "str",
                        "active": True,
                        "last_value": str(val)
                    }
                    active += 1
                else:
                    oids[key] = {"oid": oid, "active": False}
                    rejected[key] = oid
            except Exception as e:
                rejected[key] = str(e)

        # counters and supplies/trays probing (indexes)
        counter_oids = {
            "print_total": "1.3.6.1.2.1.43.10.2.1.4.1.1",
            "print_color": "1.3.6.1.2.1.43.10.2.1.4.1.2",
            "print_mono": "1.3.6.1.2.1.43.10.2.1.4.1.3",
            "prt_marker_total": "1.3.6.1.4.1.1602.1.11.2.1.1.3.1",
        }
        for k, oid in counter_oids.items():
            try:
                val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
                if val is not None:
                    oids[k] = {"oid": oid, "type": "int", "category": "counter", "active": True, "last_value": str(val)}
                    active += 1
                else:
                    oids[k] = {"oid": oid, "active": False}
                    rejected[k] = oid
            except Exception as e:
                rejected[k] = str(e)

        for idx in range(1, ENHANCED_MAX_SUPPLIES + 1):
            name_oid = f"1.3.6.1.2.1.43.11.1.1.6.1.{idx}"
            rem_oid = f"1.3.6.1.2.1.43.11.1.1.9.1.{idx}"
            max_oid = f"1.3.6.1.2.1.43.11.1.1.8.1.{idx}"
            try:
                name = snmp_get_with_fallback(ip, name_oid, community, version=snmp_version, timeout=1.5)
                rem = snmp_get_with_fallback(ip, rem_oid, community, version=snmp_version, timeout=1.5)
                mx = snmp_get_with_fallback(ip, max_oid, community, version=snmp_version, timeout=1.5)
                if name is None and rem is None and mx is None:
                    continue
                key_name = f"toner_name_{idx}"
                oids[key_name] = {"oid": name_oid, "type": "str", "category": "identity", "active": bool(name), "last_value": str(name) if name is not None else None}
                oids[f"toner_remain_{idx}"] = {"oid": rem_oid, "type": "int", "category": "supply", "active": bool(rem is not None), "last_value": str(rem) if rem is not None else None}
                oids[f"toner_max_{idx}"] = {"oid": max_oid, "type": "int", "category": "supply", "active": bool(mx is not None), "last_value": str(mx) if mx is not None else None}
                active += 1
            except Exception as e:
                rejected[f"supply_{idx}"] = str(e)

        for idx in range(1, 9):
            t_name = f"1.3.6.1.2.1.43.8.2.1.13.1.{idx}"
            t_cap = f"1.3.6.1.2.1.43.8.2.1.9.1.{idx}"
            t_lvl = f"1.3.6.1.2.1.43.8.2.1.10.1.{idx}"
            try:
                nm = snmp_get_with_fallback(ip, t_name, community, version=snmp_version, timeout=1.5)
                cap = snmp_get_with_fallback(ip, t_cap, community, version=snmp_version, timeout=1.5)
                lvl = snmp_get_with_fallback(ip, t_lvl, community, version=snmp_version, timeout=1.5)
                if nm is None and cap is None and lvl is None:
                    continue
                key = f"tray{idx}_name"
                oids[key] = {"oid": t_name, "type": "str", "category": "identity", "active": bool(nm), "last_value": str(nm) if nm is not None else None}
                oids[f"tray{idx}_cap"] = {"oid": t_cap, "type": "int", "category": "tray", "active": bool(cap is not None), "last_value": str(cap) if cap is not None else None}
                oids[f"tray{idx}_level"] = {"oid": t_lvl, "type": "int", "category": "tray", "active": bool(lvl is not None), "last_value": str(lvl) if lvl is not None else None}
                active += 1
            except Exception as e:
                rejected[f"tray_{idx}"] = str(e)

        profile = {
            "ip": ip,
            "brand": (model or "unknown").split()[0].lower() if model else "unknown",
            "device_type": device_type or "unknown",
            "scanned_at": datetime.now().isoformat(),
            "scan_ms": scan_ms,
            "oid_total": sum(1 for _ in oids),
            "oid_active": active,
            "oid_inactive": sum(1 for v in oids.values() if not v.get("active")),
            "oid_rejected": len(rejected),
            "oids": oids,
            "current_vals": {k: v.get("last_value") for k, v in oids.items() if v.get("last_value") is not None},
            "rejected_oids": rejected,
            "summary": {
                "model": model or "Unknown",
                "serial": "N/A",
                "brand": (model or "unknown").split()[0].lower() if model else "unknown",
                "total_pages": total,
                "toner_pct": None,
                "device_type": device_type or "mono",
            }
        }

        serial_oids = [
            "1.3.6.1.2.1.43.5.1.1.17.1",
            "1.3.6.1.4.1.1602.1.2.1.4.0",
        ]
        for so in serial_oids:
            try:
                s = snmp_get_with_fallback(ip, so, community, version=snmp_version, timeout=1.5)
                if s:
                    profile["summary"]["serial"] = str(s)
                    break
            except:
                continue

        path = os.path.join(os.getcwd(), "oid_profiles.json")
        try:
            data = {}
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except Exception:
                        data = {}
            data[ip] = profile
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info(f"OID profile saved for {ip} -> {path}")
        except Exception as e:
            log.error(f"Error saving oid_profiles for {ip}: {e}")
    except Exception as e:
        log.debug(f"_save_oid_profile failed for {ip}: {e}")


def detect_printer_type_from_supplies(supplies: List[Dict]) -> str:
    """تشخیص نوع پرینتر از روی مواد مصرفی"""
    toners = [s for s in supplies if s.get("type") == 3 or s.get("type_name") == "toner"]
    if not toners:
        toners = supplies
    
    color_keywords = ["cyan", "magenta", "yellow", "سیان", "مژنتا", "color", "colour"]
    for t in toners:
        name_lower = t.get("name", "").lower()
        for c in color_keywords:
            if c in name_lower:
                return "color"
    
    return "mono"


def _canon_display_percent(model: str, supply_name: str, percent: Optional[int]) -> Optional[int]:
    """Canon panel values are rounded more coarsely than raw PRT-MIB supply values."""
    if percent is None:
        return None
    model_upper = (model or "").upper()
    name_upper = (supply_name or "").upper()
    if "CANON MF" in model_upper and "CARTRIDGE 137" in name_upper and 10 < percent < 20:
        return 20
    return percent


def collect_enhanced(printer: dict, save_to_db: bool = True) -> dict:
    """
    جمع‌آوری پیشرفته داده‌ها با استفاده از روش test_toner.py
    """
    ip = printer["ip"]
    name = printer["name"]
    nickname = printer.get("nickname", "")
    community = printer.get("community", "public")
    brand = printer.get("brand", "").lower()
    start_time = time.time()
    
    log.info(f"[ENHANCED] Pulling {name} ({ip})")
    _log_to_toner_report(f"\n{'='*80}")
    _log_to_toner_report(f"🖨  {name} ({ip}) | زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # ─── تشخیص SNMP ───────────────────────────────────────────────
    snmp_version = detect_snmp_version(ip, community, timeout=2.0)
    if snmp_version is None:
        elapsed = int((time.time() - start_time) * 1000)
        _log_to_toner_report(f"   ❌ بدون پاسخ SNMP")
        return {
            "ip": ip, "name": name, "nickname": nickname, "brand": brand,
            "online": False, "last_poll": datetime.now().isoformat(), "poll_ms": elapsed,
            "error": "No SNMP response",
        }
    
    # ─── اطلاعات پایه ────────────────────────────────────────────
    sys_desc = snmp_get_with_fallback(ip, "1.3.6.1.2.1.1.1.0", community, version=snmp_version, timeout=2.0)
    sys_desc_str = str(sys_desc) if sys_desc else ""
    
    # تشخیص سنسور
    if "ECS100G" in sys_desc_str.upper():
        from core.collectors.sensor import collect_sensor
        result = collect_sensor(ip, name, community, start_time)
        result["nickname"] = nickname
        return result
    
    # ─── شمارنده‌های اصلی ─────────────────────────────────────────
    # تلاش برای خواندن total از OIDهای مختلف (برای برآورد تونر در صورت نبود سنسور)
    total = 0
    total_oids = [
        "1.3.6.1.2.1.43.10.2.1.4.1.1",  # standard
        "1.3.6.1.4.1.1129.2.3.50.1.3.21.6.1.2.1.4",  # Toshiba
    ]
    for oid in total_oids:
        val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
        if val is not None:
            try:
                total = int(val)
                if total > 0:
                    break
            except:
                pass

    # ─── خواندن اطلاعات پیشرفته ───────────────────────────────────
    supplies = walk_supplies_table(ip, community, brand, snmp_version, timeout=ENHANCED_TIMEOUT, current_total=total)
    trays = walk_input_trays(ip, community, snmp_version, timeout=ENHANCED_TIMEOUT)
    
    # ─── تشخیص رنگ ───────────────────────────────────────────────
    device_type = detect_printer_type_from_supplies(supplies) if supplies else "mono"
    if device_type == "color":
        # تلاش برای خواندن شمارنده رنگی
        color = 0
        color_oids = [
            "1.3.6.1.2.1.43.10.2.1.4.1.2",  # standard color
            "1.3.6.1.4.1.1129.2.3.50.1.3.21.6.1.2.1.1",  # Toshiba color
        ]
        for oid in color_oids:
            val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
            if val is not None:
                try:
                    color = int(val)
                    if color > 0:
                        break
                except:
                    pass
        bw = max(0, total - color) if total > 0 else 0
    else:
        color = None
        bw = total
    
    # ─── مدل و سریال ─────────────────────────────────────────────
    model = "Unknown"
    serial = "N/A"
    
    # تلاش برای خواندن مدل از OIDهای مختلف
    model_oids = [
        "1.3.6.1.2.1.43.5.1.1.16.1",  # standard
        "1.3.6.1.4.1.1129.2.3.50.1.2.3.1.3.1.1",  # Toshiba
        "1.3.6.1.4.1.11.2.3.9.1.1.3.1.1.1.1.2.0",  # HP
        "1.3.6.1.4.1.1602.1.1.1.1.0",  # Canon
    ]
    for oid in model_oids:
        val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
        if val and str(val).strip() not in ("", "N/A", "None"):
            model = str(val).strip()[:100]
            break
    
    serial_oids = [
        "1.3.6.1.2.1.43.5.1.1.17.1",
        "1.3.6.1.4.1.1129.2.3.50.1.2.4.1.8.1.1",
        "1.3.6.1.4.1.11.2.3.9.1.1.3.1.1.1.1.3.0",
        "1.3.6.1.4.1.1602.1.2.1.4.0",
    ]
    for oid in serial_oids:
        val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=2.0)
        if val and str(val).strip() not in ("", "N/A", "None"):
            serial = str(val).strip()[:100]
            break
    
    # ─── تبدیل تونرها به فرمت toners ─────────────────────────────
    toners = {}
    for s in supplies:
        if s["type_name"] in ("toner", "cartridge"):
            color_key = None
            name_lower = s["name"].lower()
            if "black" in name_lower or "bk" in name_lower:
                color_key = "black"
            elif "cyan" in name_lower or "c" in name_lower.split():
                color_key = "cyan"
            elif "magenta" in name_lower or "m" in name_lower.split():
                color_key = "magenta"
            elif "yellow" in name_lower or "y" in name_lower.split():
                color_key = "yellow"
            else:
                color_key = "black"  # fallback

            display_level = _canon_display_percent(model, s["name"], s["percent"])
            
            toners[color_key] = {
                "level": display_level,
                "status": s["status"] if s["status"] != "N/A" else "unknown",
                "name": s["name"],
                "remaining": s["remaining"],
                "max": s["max"],
            }
    
    # اگر تونری پیدا نشد، یک تونر مشکی پیش‌فرض
    if not toners:
        toners["black"] = {"level": None, "status": "unknown", "name": "Toner", "remaining": -1, "max": -1}

    # ─── اعمال override دستی تونر بر اساس مصرف صفحات ─────────────────
    prev_override = store._prev.get(ip) or {}
    override_color = prev_override.get('override_color')
    if prev_override.get('manual_override') and override_color and override_color in toners:
        snmp_level = toners[override_color].get('level')
        final_level = apply_toner_override(ip, total, snmp_level, color=override_color)
        if final_level is not None:
            toners[override_color]['level'] = final_level
            if final_level == 0:
                toners[override_color]['status'] = 'empty'
            elif final_level <= 5:
                toners[override_color]['status'] = 'critical'
            elif final_level <= 15:
                toners[override_color]['status'] = 'low'
            else:
                toners[override_color]['status'] = 'ok'

    # ─── هشدارها ─────────────────────────────────────────────────
    alerts = []
    for s in supplies:
        if s["status"] in ("critical", "empty", "low") and s["type_name"] in ("toner", "cartridge"):
            alerts.append({
                "message": f"{s['name']}: {s['status']} ({s['percent']}%)",
                "code": s["index"]
            })
    
    # ─── uptime ──────────────────────────────────────────────────
    ut_raw = snmp_get_with_fallback(ip, "1.3.6.1.2.1.1.3.0", community, version=snmp_version, timeout=2.0)
    ut = int(ut_raw) if ut_raw else 0
    us = ut // 100
    uptime_str = f"{us//86400}d {(us%86400)//3600:02d}:{(us%3600)//60:02d}" if ut else "N/A"
    
    elapsed = int((time.time() - start_time) * 1000)
    
    # ─── ثبت در toner_report.txt ─────────────────────────────────
    _log_to_toner_report(f"   SNMP v{snmp_version} | مدل: {model} | نوع: {device_type}")
    _log_to_toner_report(f"   کل صفحات: {total:,} | رنگی: {color if color else 0:,} | سیاه‌سفید: {bw:,}")
    for color_key, t in toners.items():
        pct_str = f"{t['level']}%" if t['level'] is not None else "N/A"
        status_icon = {"ok": "✅", "low": "🟡", "critical": "🟠", "empty": "🔴"}.get(t["status"], "❓")
        _log_to_toner_report(f"   {color_key}: {pct_str} {status_icon}")
    _log_to_toner_report(f"   زمان پاسخ: {elapsed}ms")
    try:
        # ذخیره پروفایل OID برای این دستگاه (به‌روز رسانی یا ساخت جدید)
        _save_oid_profile(ip, community, snmp_version, model, device_type, total, color, bw, supplies, trays, elapsed)
    except Exception:
        log.debug("Saving oid profile failed, continuing")
    
    # ─── ذخیره در دیتابیس (printer_counters) ────────────────────
    if save_to_db:
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH, timeout=10.0)
            c = conn.cursor()

            black_level = None
            if toners.get("black", {}).get("level") is not None:
                black_level = toners["black"]["level"]
            else:
                for t in toners.values():
                    if t.get("level") is not None:
                        black_level = t["level"]
                        break
            
            # ذخیره مقادیر قبلی در جدول printer_counters و حفظ metadata override
            c.execute('''
                INSERT OR REPLACE INTO printer_counters 
                (ip, print_total, full_color, black_white, toner_level, manual_override, override_color, override_base_level, override_start_total, override_start_toner, yield_per_page, updated_at, device_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ip,
                total,
                color if color else 0,
                bw,
                black_level,
                prev_override.get('manual_override', 0),
                prev_override.get('override_color'),
                prev_override.get('override_base_level'),
                prev_override.get('override_start_total'),
                prev_override.get('override_start_toner'),
                prev_override.get('yield_per_page', 2000),
                datetime.now().isoformat(),
                device_type
            ))
            
            # ذخیره اطلاعات تونرها در فیلد alert_codes (JSON)
            # این کار اطلاعات تونر را هم نگهداری می‌کند
            import json
            toner_data = {
                "toners": {
                    k: {"level": v["level"], "status": v["status"], "name": v["name"]}
                    for k, v in toners.items()
                },
                "supplies": [
                    {"name": s["name"], "percent": s["percent"], "status": s["status"], "type": s["type_name"]}
                    for s in supplies if s["percent"] is not None
                ]
            }
            c.execute('''
                UPDATE printer_counters SET alert_codes = ?, last_alert_codes = ? WHERE ip = ?
            ''', (json.dumps(toner_data, ensure_ascii=False), json.dumps([a["code"] for a in alerts]), ip))
            
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"خطا در ذخیره enhanced data در دیتابیس: {e}")
    
    # ─── ثبت رویداد PRINT / REFILL ────────────────────────────────
    prev = store._prev.get(ip) or {}
    black_level = None
    if toners.get("black", {}).get("level") is not None:
        black_level = toners["black"]["level"]
    else:
        for t in toners.values():
            if t.get("level") is not None:
                black_level = t["level"]
                break
    prev_toner = prev.get("toner_level")
    _counters_event(ip, total, prev, alerts, [a["code"] for a in alerts],
                    full_color=color, black_white=bw, paper_size=None,
                    current_toner_level=black_level, prev_toner_level=prev_toner,
                    uptime=ut)
    
    return {
        "ip": ip, "name": name, "nickname": nickname, "brand": brand,
        "device_type": device_type,
        "online": True,
        "last_poll": datetime.now().isoformat(),
        "poll_ms": elapsed,
        "device": {
            "model": model,
            "serial": serial,
            "firmware": "N/A",
            "uptime_str": uptime_str,
        },
        "counters": {
            "total": total,
            "full_color": color if color else None,
            "black_white": bw,
            "printer": total,
            "copy": total,  # استفاده از total به جای None
            "fax": None,    # fax معمولاً شامل نمی‌شود
            "list": total,  # استفاده از total به جای None
            "scan_fc": None,      # عموماً در دسترس نیست
            "scan_bw": None,      # عموماً در دسترس نیست
            "scan_net_fc": None,  # عموماً در دسترس نیست
            "scan_net_bw": None,  # عموماً در دسترس نیست
        },
        "paper_sizes": {},
        "trays": trays,
        "toners": toners,
        "alerts": alerts,
    }