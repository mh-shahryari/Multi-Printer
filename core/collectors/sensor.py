"""جمع‌آوری داده از سنسور ECS100G با SNMP v1 (OIDهای واقعی)"""

import time
import logging
from datetime import datetime
from core.snmp.protocol import snmp_get
from core import store

log = logging.getLogger("PrinterMonitor")

# OIDهای واقعی ECS100G (استخراج شده از snmpwalk)
SENSOR_OIDS = {
    "model":        "1.3.6.1.4.1.47206.1.0",      # مدل دستگاه
    "serial":       "1.3.6.1.4.1.47206.2.0",      # شماره سریال
    "uptime":       "1.3.6.1.2.1.1.3.0",          # آپتایم (اضافه شده)
    "temp1":        "1.3.6.1.4.1.47206.110.1.2.0", # دمای پورت ۱ (تقسیم بر ۱۰)
    "temp1_status": "1.3.6.1.4.1.47206.110.1.1.0", # وضعیت سنسور دمای ۱
    "temp2":        "1.3.6.1.4.1.47206.110.2.2.0", # دمای پورت ۲
    "temp2_status": "1.3.6.1.4.1.47206.110.2.1.0",
    "hum1":         "1.3.6.1.4.1.47206.111.1.2.0", # رطوبت پورت ۱ (تقسیم بر ۱۰)
    "hum1_status":  "1.3.6.1.4.1.47206.111.1.1.0",
    "hum2":         "1.3.6.1.4.1.47206.111.2.2.0", # رطوبت پورت ۲
    "hum2_status":  "1.3.6.1.4.1.47206.111.2.1.0",
}


def _safe_divide_10(val):
    """تبدیل امن مقدار SNMP به مقدار واقعی (تقسیم بر ۱۰)"""
    try:
        if val is not None:
            return round(int(val) / 10, 1)
    except (ValueError, TypeError):
        pass
    return None


def collect_sensor(ip: str, name: str, community: str, start: float) -> dict:
    try:
        def g(oid_key):
            """خواندن OID با SNMPv1 و timeout"""
            if time.time() - start > 10.0:  # تایم‌اوت کلی ۱۰ ثانیه
                return None
            oid = SENSOR_OIDS.get(oid_key)
            if not oid:
                return None
            return snmp_get(ip, oid, community, timeout=2.0, version=1)

        # خواندن همه مقادیر
        values = {key: g(key) for key in SENSOR_OIDS}

        # بررسی آنلاین بودن
        if values.get("model") is None and values.get("temp1") is None:
            elapsed = int((time.time() - start) * 1000)
            return {
                "ip": ip, "name": name, "brand": "sensor",
                "online": False,
                "last_poll": datetime.now().isoformat(),
                "poll_ms": elapsed,
                "error": "No SNMP response"
            }

        model = str(values.get("model", "")).strip() or "ECS100G"
        serial = str(values.get("serial", "")).strip() or "N/A"

        # آپتایم
        ut_raw = values.get("uptime")
        ut = int(ut_raw) if ut_raw else 0
        us = ut // 100
        uptime_str = f"{us//86400}d {(us%86400)//3600:02d}:{(us%3600)//60:02d}" if ut else "N/A"

        # تبدیل مقادیر دما و رطوبت (تقسیم بر ۱۰)
        temp1 = _safe_divide_10(values.get("temp1"))
        temp2 = _safe_divide_10(values.get("temp2"))
        hum1  = _safe_divide_10(values.get("hum1"))
        hum2  = _safe_divide_10(values.get("hum2"))

        # وضعیت‌ها (1 = active, 0 = inactive)
        t1_st = "active" if values.get("temp1_status") == 1 else "inactive"
        t2_st = "active" if values.get("temp2_status") == 1 else "inactive"
        h1_st = "active" if values.get("hum1_status")  == 1 else "inactive"
        h2_st = "active" if values.get("hum2_status")  == 1 else "inactive"

        elapsed = int((time.time() - start) * 1000)
        log.info(f"  ✓ {name} [sensor] T1={temp1}°C T2={temp2}°C H1={hum1}% H2={hum2}% {elapsed}ms")

        return {
            "ip": ip, "name": name, "brand": "sensor",
            "online": True,
            "last_poll": datetime.now().isoformat(),
            "poll_ms": elapsed,
            "device": {
                "model": model,
                "serial": serial,
                "firmware": model,
                "uptime_str": uptime_str,  # ← حالا مقدار واقعی دارد
            },
            "counters": {
                "temp1": temp1, "temp2": temp2,
                "hum1": hum1, "hum2": hum2,
                "temp1_status": t1_st, "temp2_status": t2_st,
                "hum1_status": h1_st, "hum2_status": h2_st,
            },
            "paper_sizes": {},
            "trays": [],
            "toners": {},
            "alerts": [],
        }
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.exception(f"  ✗ {name} [sensor] error: {e}")
        return {
            "ip": ip, "name": name, "brand": "sensor",
            "online": False,
            "last_poll": datetime.now().isoformat(),
            "poll_ms": elapsed,
            "device": {"model": "ECS100G", "serial": "N/A", "firmware": "N/A", "uptime_str": "N/A"},
            "counters": {"temp1": None, "temp2": None, "hum1": None, "hum2": None},
            "paper_sizes": {}, "trays": [], "toners": {},
            "alerts": [{"message": f"Collection error: {e}", "code": 9999}],
        }