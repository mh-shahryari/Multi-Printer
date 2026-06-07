# core/poller.py

"""
چرخه polling:
- collect: جمع‌آوری داده از یک پرینتر با routing به collector مناسب
- poll_all: polling موازی همه پرینترها
- polling_loop: حلقه بی‌نهایت با POLL_INTERVAL
"""

import time
import threading
import logging
from datetime import datetime

from config.settings import POLL_INTERVAL
from core import store
from core.database import add_event
from core.snmp.protocol import snmp_get_with_fallback
from core.snmp.oid_map import OIDS
from core.collectors.base import si, detect_brand

# 🔥 تغییر: استفاده از enhanced_collector به جای کالکتورهای جداگانه
from core.collectors.base_enhanced import collect_enhanced

# کالکتورهای قدیمی (فقط برای سنسور保留)
from core.collectors.sensor import collect_sensor

log = logging.getLogger("PrinterMonitor")

# قفل برای جلوگیری از اجرای هم‌زمان poll_all
_polling_lock = threading.Lock()


def collect(printer: dict) -> dict:
    """
    جمع‌آوری داده از یک پرینتر.
    🔥 تغییر: استفاده از enhanced_collector برای همه دستگاه‌ها (به جز سنسور)
    """
    ip = printer["ip"]
    name = printer["name"]
    nickname = printer.get("nickname", "")
    community = printer.get("community", "public")
    brand = printer.get("brand", "").lower()
    device_type = printer.get("device_type", "unknown")

    log.info(f"Pulling {name} ({ip}) [{brand or 'auto'}] - using enhanced collector")
    start = time.time()

    # تست اولیه برای آنلاین بودن
    test = snmp_get_with_fallback(ip, "1.3.6.1.2.1.1.1.0", community, timeout=2.0)
    if test is None:
        test = snmp_get_with_fallback(ip, OIDS.get("uptime", "1.3.6.1.2.1.1.3.0"), community, timeout=2.0)
    online = test is not None

    with store.data_lock:
        was_online = store.printer_data.get(ip, {}).get("online", None)

    if not online:
        if was_online:
            add_event(ip, "STATUS", {"message": "دستگاه آفلاین شد", "severity": "error"})
        elapsed = int((time.time() - start) * 1000)
        return {
            "ip": ip, "name": name, "nickname": nickname, "brand": brand, "device_type": device_type,
            "online": False,
            "last_poll": datetime.now().isoformat(),
            "poll_ms": elapsed,
            "error": "Device unreachable",
        }

    if was_online is False:
        add_event(ip, "STATUS", {"message": "دستگاه آنلاین شد", "severity": "success"})

    # تشخیص برند (اگر قبلاً مشخص نبود)
    if brand == "sensor":
        # سنسورها با کالکتور مخصوص خود
        result = collect_sensor(ip, name, community, start)
        result["nickname"] = nickname
        result["device_type"] = "sensor"
        return result
    
    if not brand or brand == "unknown":
        brand = detect_brand(ip, community)
        log.info(f"  → برند شناسایی شد: {brand}")
        with store.printers_lock:
            for p in store.PRINTERS:
                if p["ip"] == ip:
                    p["brand"] = brand
                    store.save_printers(store.PRINTERS)
                    break

    # 🔥 استفاده از enhanced_collector برای همه پرینترها
    try:
        result = collect_enhanced(printer)
        result["nickname"] = nickname
        result["device_type"] = result.get("device_type", device_type)
        return result
    except Exception as e:
        log.error(f"Enhanced collector failed for {ip}: {e}, falling back to basic")
        # Fallback به اطلاعات پایه در صورت خطا
        elapsed = int((time.time() - start) * 1000)
        return {
            "ip": ip, "name": name, "nickname": nickname, "brand": brand,
            "online": True,
            "last_poll": datetime.now().isoformat(),
            "poll_ms": elapsed,
            "device": {"model": "Unknown", "serial": "N/A", "firmware": "N/A", "uptime_str": "N/A"},
            "counters": {"total": 0, "full_color": None, "black_white": 0},
            "paper_sizes": {}, "trays": [], "toners": {}, "alerts": [],
            "error": str(e),
        }


def poll_one(p: dict):
    """Poll یک پرینتر واحد"""
    data = collect(p)
    with store.data_lock:
        store.printer_data[p["ip"]] = data


def poll_all():
    """اجرای poll برای همه پرینترها با جلوگیری از اجرای هم‌زمان"""
    with _polling_lock:
        with store.printers_lock:
            current = list(store.PRINTERS)

        log.info(f"🔄 Starting pull cycle for {len(current)} devices (interval={POLL_INTERVAL}s)")
        results = {}
        processed_ips = set()

        def _poll(p):
            ip = p["ip"]
            if ip not in processed_ips:
                processed_ips.add(ip)
                results[ip] = collect(p)

        threads = [threading.Thread(target=_poll, args=(p,), daemon=True) for p in current]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=45)  # افزایش timeout به 45 ثانیه

        with store.data_lock:
            store.printer_data.update(results)
            store.poll_stats["count"] += 1
            store.poll_stats["last"] = datetime.now().isoformat()
            store.poll_stats["errors"] = sum(1 for d in results.values() if not d.get("online"))

        log.info(f"✅ Pull cycle completed: {len(results)} devices, "
                 f"{store.poll_stats['errors']} errors, "
                 f"next pull in {POLL_INTERVAL}s")


def polling_loop():
    """حلقه بی‌نهایت polling"""
    # poll_all در startup یک چرخه فوری اجرا می‌کند؛ این sleep مانع اجرای
    # بلافاصلهٔ چرخهٔ دوم و ثبت PRINTهای تکراری در چند ثانیهٔ اول می‌شود.
    time.sleep(POLL_INTERVAL)
    while True:
        try:
            poll_all()
        except Exception as e:
            log.error(f"Error in pull loop: {e}")
        time.sleep(POLL_INTERVAL)