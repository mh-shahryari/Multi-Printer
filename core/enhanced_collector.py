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

from config.settings import VALIDATION_LOG_FILE, TONER_ALERT_THRESHOLDS
from core.snmp.protocol import snmp_get_with_fallback, _detect_snmp_version
from core.snmp.oid_map import OIDS
from core import store
from core.collectors.base import _counters_event, apply_toner_override, _bootstrap_yield_from_history, get_pages_since_last_reset
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


# ─── الگوهای تشخیص رنگ تونر (دقیق‌تر) ─────────────────────────────
import re as _re
_TONER_COLOR_PATTERNS = {
    "black": _re.compile(r'\b(black|bk)\b', _re.IGNORECASE),
    "cyan": _re.compile(r'\b(cyan)\b', _re.IGNORECASE),
    "magenta": _re.compile(r'\b(magenta|mgt)\b', _re.IGNORECASE),
    "yellow": _re.compile(r'\b(yellow)\b', _re.IGNORECASE),
}

def _detect_toner_color(name: str) -> Optional[str]:
    """✅ باگ #8: تشخیص دقیق رنگ تونر با regex (جلوگیری از match اشتباه)"""
    if not name:
        return None
    for color, pattern in _TONER_COLOR_PATTERNS.items():
        if pattern.search(name):
            return color
    return None

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


def _save_counters_to_db(ip: str, total: int, color, bw, black_level, 
                          prev_override: dict, device_type: str,
                          toners: dict, supplies: list, alerts: list):
    """✅ باگ #12: ذخیره امن در دیتابیس با context manager"""
    try:
        from core.database import db_connection
        with db_connection(commit=True) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO printer_counters 
                (ip, print_total, full_color, black_white, toner_level, 
                 manual_override, override_color, override_base_level, 
                 override_start_total, override_start_toner, yield_per_page, 
                 updated_at, device_type)
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
            
            # ذخیره اطلاعات تونرها
            toner_data = {
                "toners": {
                    k: {"level": v["level"], "status": v["status"], "name": v.get("name", "")}
                    for k, v in toners.items()
                },
                "supplies": [
                    {"name": s["name"], "percent": s["percent"], "status": s["status"], "type": s["type_name"]}
                    for s in supplies if s["percent"] is not None
                ]
            }
            # 🔥 اصلاح: ذخیره toner_data در alert_codes باعث آلودگی دیتابیس می‌شد
            # در عوض فقط کدهای هشدار در alert_codes و لیست تونرها در last_alert_codes ذخیره می‌شود
            alert_codes_json = json.dumps([a["code"] for a in alerts], ensure_ascii=False)
            toner_data_json = json.dumps(toner_data, ensure_ascii=False)
            
            conn.execute('''
                UPDATE printer_counters SET alert_codes = ?, last_alert_codes = ? WHERE ip = ?
            ''', (alert_codes_json, toner_data_json, ip))
    except Exception as e:
        log.error(f"خطا در ذخیره enhanced data در دیتابیس: {e}")


def detect_snmp_version(ip: str, community: str = "public", timeout: float = 2.0) -> Optional[int]:
    """
    تشخیص نسخه SNMP با تکیه بر cache و negative-cache ماژول protocol.
    بازگشت: 1, 2, یا None
    """
    return _detect_snmp_version(ip, community, probe_timeout=timeout)


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
                        except Exception:
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
                except Exception:
                    pass
    
    elif brand == "canon":
        for oid in CANON_ALTERNATE_OIDS:
            val = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=timeout)
            if val is not None:
                try:
                    int_val = int(val)
                    if 0 <= int_val <= 100:
                        return int_val
                except Exception:
                    pass
    
    return None


def walk_supplies_table(ip: str, community: str, brand: str = "unknown", 
                        snmp_version: int = None, timeout: float = 2.0, current_total: int = None) -> List[Dict]:
    """
    Walk کامل روی جدول prtMarkerSuppliesTable
    بازگشت: لیستی از دیکشنری‌های حاوی اطلاعات کارتریج‌ها
    """
    supplies = []
    
    # برای Brother، اول روش اختصاصی امتحان می‌شود.
    # اگر سطح تونر از OID اختصاصی به دست نیاید (مثل بعضی مدل‌های NC-8300h)،
    # به روش استاندارد prtMarkerSuppliesTable fallback می‌کنیم.
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
            except Exception:
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
            except Exception:
                pass

        # اگر تونر اختصاصی با موفقیت خوانده شد، همان را برگردان.
        # در غیر این صورت، به روش عمومی prtMarkerSuppliesTable ادامه می‌دهیم.
        if any(s.get("type_name") == "toner" for s in supplies):
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
            # Brother برخی consumableها را با typeهای غیر دقیق گزارش می‌کند.
            # برای نمایش صحیح درام و تونر، از نام مصرفی هم کمک می‌گیریم.
            if brand == "brother":
                lowered_name = name_str.lower()
                if "drum" in lowered_name:
                    type_name = "drum"
                elif "toner" in lowered_name:
                    type_name = "toner"

            percent = None
            max_int = -2
            rem_int = -2
            
            try:
                if max_val is not None and str(max_val).lstrip('-').isdigit():
                    max_int = int(max_val)
                if rem_val is not None and str(rem_val).lstrip('-').isdigit():
                    rem_int = int(rem_val)
                
                # ✅ باگ #20: فقط وقتی max_int معتبره درصد حساب کن
                # حذف شرط elif که فرض می‌کرد rem_int بین 0-100 = درصد
                if max_int > 0 and rem_int >= 0:
                    percent = round(rem_int / max_int * 100)
            except (ValueError, TypeError) as e:
                log.warning(f"Supply conversion error for {ip} idx={idx}: max={max_val}, rem={rem_val}: {e}")
            
            # اگر درصد نداریم، OIDهای جایگزین را امتحان کن
            if percent is None and brand in ["hp", "canon"]:
                alt_percent = try_alternative_oids(ip, community, brand, name_str, snmp_version, timeout)
                if alt_percent is not None:
                    percent = alt_percent
                    rem_int = alt_percent
                    max_int = 100

            # وضعیت
            status = "N/A"
            if percent is not None:
                if percent == 0:
                    status = "empty"
                elif percent <= 10:
                    status = "critical"
                elif percent <= 25:
                    status = "low"
                else:
                    status = "ok"
            elif rem_int == -2:
                # ✅ باگ #15: وقتی max معتبر نداریم، هرگز rem را به‌عنوان درصد فرض نکن.
                # این حالت معمولاً یعنی سنسور/مقدار قابل‌اعتماد در دسترس نیست.
                status = "no_sensor" if name_str and name_str != "Unknown" else "not_supported"
                log.info(f"  [{ip}] Supply {idx} ({name_str}): no sensor data available")
            elif rem_int == -3:
                status = "not_supported"

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
            except Exception:
                cap_int = 0
            
            try:
                if level_val is not None and str(level_val).lstrip('-').isdigit():
                    level_int = int(level_val)
                else:
                    level_int = -2
            except Exception:
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
            except Exception:
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



def _read_toshiba_value(ip: str, community: str, key: str, snmp_version: int, default=None, timeout: float = 2.0):
    oid = OIDS.get(key)
    if not oid:
        return default
    value = snmp_get_with_fallback(ip, oid, community, version=snmp_version, timeout=timeout)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



def _collect_toshiba_job_data(ip: str, community: str, snmp_version: int, total: int, color: Optional[int]):
    """خواندن شمارنده‌های اختصاصی Toshiba برای جلوگیری از overcount و تکمیل UI/log."""
    a3_total = _read_toshiba_value(ip, community, "a3_total", snmp_version, default=None)
    a4_total = _read_toshiba_value(ip, community, "a4_total", snmp_version, default=None)
    prev = store._prev.get(ip) or {}
    prev_a3 = prev.get("a3_total")
    prev_a4 = prev.get("a4_total")

    paper_size = None
    if a3_total is not None and a4_total is not None and prev_a3 is not None and prev_a4 is not None:
        delta_a3 = a3_total - prev_a3
        delta_a4 = a4_total - prev_a4
        if delta_a3 > 0 and delta_a4 == 0:
            paper_size = "Large (A3/B4)"
        elif delta_a4 > 0 and delta_a3 == 0:
            paper_size = "Small (A4/A5)"
        elif delta_a3 > 0 and delta_a4 > 0:
            paper_size = "Mixed"

    # برای ثبت رویداد، به total خام تکیه می‌کنیم و twin را وارد محاسبه pages نمی‌کنیم
    # چون در برخی مدل‌های Toshiba دو فاز update باعث duplicate PRINT می‌شود.
    bw_for_event = max(0, total - (color or 0)) if total is not None else None

    copy_fc = _read_toshiba_value(ip, community, "print_copy_fc", snmp_version, default=0)
    copy_bw = _read_toshiba_value(ip, community, "print_copy_bw", snmp_version, default=0)
    printer_fc = _read_toshiba_value(ip, community, "print_printer_fc", snmp_version, default=0)
    printer_bw = _read_toshiba_value(ip, community, "print_printer_bw", snmp_version, default=0)
    twin = _read_toshiba_value(ip, community, "print_twin", snmp_version, default=0)
    fax = _read_toshiba_value(ip, community, "print_fax", snmp_version, default=None)
    list_count = _read_toshiba_value(ip, community, "print_list", snmp_version, default=None)
    scan_fc = _read_toshiba_value(ip, community, "scan_fc", snmp_version, default=None)
    scan_bw = _read_toshiba_value(ip, community, "scan_bw", snmp_version, default=None)
    scan_net_fc = _read_toshiba_value(ip, community, "scan_net_fc", snmp_version, default=None)
    scan_net_bw = _read_toshiba_value(ip, community, "scan_net_bw", snmp_version, default=None)

    paper_sizes = {}
    for key in ["a4", "a3", "a4r", "a5", "b4"]:
        total_key = _read_toshiba_value(ip, community, f"{key}_total", snmp_version, default=None)
        fc_key = _read_toshiba_value(ip, community, f"{key}_fc", snmp_version, default=None)
        bw_key = _read_toshiba_value(ip, community, f"{key}_bw", snmp_version, default=None)
        if total_key is not None or fc_key is not None or bw_key is not None:
            paper_sizes[key.upper()] = {
                "total": total_key or 0,
                "fc": fc_key or 0,
                "bw": bw_key or 0,
            }

    return {
        "paper_size": paper_size,
        "a3_total": a3_total,
        "a4_total": a4_total,
        "black_white_for_event": bw_for_event,
        "counters": {
            "printer": (printer_fc + printer_bw) if (printer_fc is not None and printer_bw is not None) else total,
            "printer_fc": printer_fc,
            "printer_bw": printer_bw,
            "copy": (copy_fc + copy_bw) if (copy_fc is not None and copy_bw is not None) else None,
            "copy_fc": copy_fc,
            "copy_bw": copy_bw,
            "fax": fax,
            "list": list_count,
            "twin": twin,
            "scan_fc": scan_fc,
            "scan_bw": scan_bw,
            "scan_net_fc": scan_net_fc,
            "scan_net_bw": scan_net_bw,
        },
        "paper_sizes": paper_sizes,
    }


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
    # تلاش برای خواندن total از OIDهای مختلف
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
                # ✅ باگ #12: validation مقدار total (جلوگیری از مقادیر منفی)
                if total < 0:
                    log.warning(f"Negative total ({total}) for {ip}, using 0")
                    total = 0
                elif total > 0:
                    break
            except (ValueError, TypeError) as e:
                log.warning(f"Total conversion error for {ip}: {val!r}: {e}")

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
                except Exception:
                    pass
        # ✅ باگ #16: validation مقدار color (جلوگیری از color > total)
        if color > total and total > 0:
            log.warning(f"color ({color}) > total ({total}) for {ip}, correcting")
            color = None
            bw = total
        elif color > 0:
            bw = max(0, total - color)
        else:
            color = None
            bw = total
    else:
        color = None
        bw = total

    is_toshiba = brand == "toshiba" or "toshiba" in sys_desc_str.lower()
    toshiba_data = None
    if is_toshiba:
        try:
            toshiba_total = _read_toshiba_value(ip, community, "print_total", snmp_version, default=None)
            if toshiba_total is not None and toshiba_total >= 0:
                total = toshiba_total
            toshiba_color = _read_toshiba_value(ip, community, "print_fc", snmp_version, default=None)
            if toshiba_color is not None:
                color = min(toshiba_color, total) if total is not None else toshiba_color
                device_type = "color" if color > 0 or device_type == "color" else device_type
            bw = max(0, total - (color or 0)) if total is not None else bw
            toshiba_data = _collect_toshiba_job_data(ip, community, snmp_version, total, color)
        except Exception as exc:
            log.warning("Toshiba vendor counters unavailable for %s: %s", ip, exc)
            toshiba_data = None
    
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
        if s["type_name"] in ("toner", "cartridge", "drum", "opc"):
            lowered_name = str(s.get("name", "")).lower()
            if s["type_name"] in ("drum", "opc") or "drum" in lowered_name:
                color_key = "drum"
                display_level = s["percent"]
            else:
                # ✅ باگ #8: استفاده از تشخیص رنگ دقیق با regex
                color_key = _detect_toner_color(s["name"]) or "black"
                display_level = _canon_display_percent(model, s["name"], s["percent"])

            toners[color_key] = {
                "level": display_level,
                "status": s["status"] if s["status"] != "N/A" else "unknown",
                "name": s["name"],
                "remaining": s["remaining"],
                "max": s["max"],
                "index": s.get("index"),
            }

    # اگر تونری پیدا نشد، یک تونر مشکی پیش‌فرض
    if not toners:
        toners["black"] = {"level": None, "status": "unknown", "name": "Toner", "remaining": -1, "max": -1}

    # فیلدهای مصرف برای همه برندها به صورت سازگار نگه داشته می‌شوند؛ اگر داده‌ای
    # وجود نداشته باشد UI آن را نمایش نمی‌دهد.
    for toner_data in toners.values():
        toner_data.setdefault("usage", None)
        toner_data.setdefault("usage_m", None)

    if is_toshiba:
        for color_key in ("black", "cyan", "magenta", "yellow"):
            if color_key not in toners:
                continue
            usage_raw = _read_toshiba_value(ip, community, f"toner_{color_key}_usage", snmp_version, default=None)
            if usage_raw is not None and usage_raw > 0:
                toners[color_key]["usage"] = usage_raw
                toners[color_key]["usage_m"] = round(usage_raw / 1_000_000, 2)

    # ─── اعمال override دستی تونر بر اساس مصرف صفحات ─────────────────
    prev_override = store._prev.get(ip) or {}
    if prev_override.get('yield_per_page', 2000) == 2000 and not prev_override.get('force_estimate'):
        boot = _bootstrap_yield_from_history(ip, prev_override)
        if boot:
            prev_override = store._prev.get(ip) or prev_override

    override_color = prev_override.get('override_color')
    pages_since_last_reset = get_pages_since_last_reset(prev_override, total)
    if prev_override.get('manual_override') and override_color and override_color in toners:
        snmp_level = toners[override_color].get('level')
        final_level = apply_toner_override(ip, total, snmp_level, color=override_color)
        if final_level is not None:
            toners[override_color]['level'] = final_level
            if prev_override.get('force_estimate'):
                toners[override_color]['source'] = 'forced_estimate'
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
    for color_key, toner in toners.items():
        level = toner.get("level")
        if level is None:
            continue
        try:
            level = int(level)
        except (TypeError, ValueError):
            continue
        if level > TONER_ALERT_THRESHOLDS.get("warning", 15):
            continue
        status = "critical" if level <= TONER_ALERT_THRESHOLDS.get("critical", 5) else "low"
        toner["status"] = "empty" if level == 0 else status
        alerts.append({
            "message": f"{toner.get('name', color_key)}: {toner['status']} ({level}%)",
            "code": toner.get("index") or color_key,
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
    
    # ✅ باگ #2 + #5 + #12: حذف نوشتن مستقیم DB
    # نوشتن در دیتابیس حالا بعد از _counters_event انجام می‌شه
    # (به خطوط بعدی مراجعه کنید)
    
    # ─── ثبت رویداد PRINT / REFILL ────────────────────────────────
    # ✅ باگ #2: ثبت رویداد BEFORE نوشتن در دیتابیس
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
    paper_size = (toshiba_data or {}).get("paper_size")
    a3_total = (toshiba_data or {}).get("a3_total")
    a4_total = (toshiba_data or {}).get("a4_total")
    bw_for_event = (toshiba_data or {}).get("black_white_for_event", bw)

    # ✅ باگ #2: ثبت رویداد اول (قبل از نوشتن DB)
    _counters_event(ip, total, prev, alerts, [a["code"] for a in alerts],
                    full_color=color, black_white=bw_for_event, paper_size=paper_size,
                    current_toner_level=black_level, prev_toner_level=prev_toner,
                    uptime=ut, a3_total=a3_total, a4_total=a4_total,
                    poll_timestamp=datetime.fromtimestamp(start_time).isoformat())
    
    # ✅ باگ #5: منبع حقیقت فقط PrevStore/`printer_counters` است.
    # از نوشتن مستقیم و مضاعف در دیتابیس خودداری می‌کنیم.
    if save_to_db:
        log.debug("Enhanced snapshot persisted via PrevStore only for %s", ip)

    vendor_counters = (toshiba_data or {}).get("counters", {})
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
            "printer": vendor_counters.get("printer", total),
            "printer_fc": vendor_counters.get("printer_fc"),
            "printer_bw": vendor_counters.get("printer_bw"),
            "copy": vendor_counters.get("copy"),
            "copy_fc": vendor_counters.get("copy_fc"),
            "copy_bw": vendor_counters.get("copy_bw"),
            "fax": vendor_counters.get("fax"),
            "list": vendor_counters.get("list"),
            "twin": vendor_counters.get("twin"),
            "scan_fc": vendor_counters.get("scan_fc"),
            "scan_bw": vendor_counters.get("scan_bw"),
            "scan_net_fc": vendor_counters.get("scan_net_fc"),
            "scan_net_bw": vendor_counters.get("scan_net_bw"),
            "pages_since_last_reset": pages_since_last_reset,
        },
        "paper_sizes": (toshiba_data or {}).get("paper_sizes", {}),
        "trays": trays,
        "toners": toners,
        "alerts": alerts,
    }