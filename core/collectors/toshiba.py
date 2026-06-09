"""
جمع‌آوری داده از Toshiba e-STUDIO از طریق SNMP + HTTP scraping
با پشتیبانی از تشخیص سایز کاغذ و محاسبه دقیق تونر
"""

import re
import time
import logging
from datetime import datetime

from core.snmp.protocol import snmp_get_bulk, snmp_get_with_fallback
from core.snmp.oid_map import OIDS, PAPER_SIZE_MAP, TONER_STATUS, TONER_LEVEL
from core.collectors.base import si, ss, _counters_event, validate_counter_consistency
from core import store
from core.database import add_event

log = logging.getLogger("PrinterMonitor")

NE_LEVEL = {5: 25, 6: 20, 7: 10, 8: 0, 9: 5}

# ✅ باگ #10: کش HTTP scrape برای کاهش timeout و افزایش دقت
_toner_scrape_cache = {}  # ip → (timestamp, result)
_TONER_CACHE_TTL = 300  # ۵ دقیقه

# تنظیمات validation log
from config.settings import VALIDATION_LOG_FILE

def _log_validation_error(ip: str, error_type: str, details: str):
    """ثبت خطا در فایل validation log"""
    try:
        timestamp = datetime.now().isoformat()
        with open(VALIDATION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] IP: {ip} | Type: toshiba_{error_type}\n")
            f.write(f"  Details: {details}\n\n")
    except Exception as e:
        log.exception("خطا در نوشتن validation log: %s", e)


def _scrape_toshiba_toners(ip: str, timeout: float = 4.0):
    """درصد دقیق تونر را از پنل TopAccess می‌خواند."""
    # ✅ باگ #10: بررسی کش قبل از درخواست HTTP
    now = time.time()
    if ip in _toner_scrape_cache:
        ts, cached_result = _toner_scrape_cache[ip]
        if now - ts < _TONER_CACHE_TTL:
            log.debug(f"Toshiba toner cache hit for {ip}")
            return cached_result
    
    html = None
    url = f"http://{ip}/?MAIN=DEVICE"

    try:
        import requests as _req
        resp = _req.get(url, timeout=timeout,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; PrinterMonitor/1.0)"},
                        allow_redirects=True)
        if resp.status_code == 200:
            html = resp.text
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"Toshiba scrape (requests) {ip}: {e}")

    if html is None:
        try:
            import urllib.request as _ur
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PrinterMonitor/1.0)"})
            with _ur.urlopen(req, timeout=timeout) as resp:
                html = resp.read(200_000).decode("utf-8", errors="replace")
        except Exception as e:
            log.debug(f"Toshiba scrape (urllib) {ip}: {e}")

    if not html:
        return None

    result = {}
    patterns = [
        ("yellow",  r'Yellow\(Y\).*?(\d{1,3})%',  re.DOTALL),
        ("magenta", r'Magenta\(M\).*?(\d{1,3})%', re.DOTALL),
        ("cyan",    r'Cyan\(C\).*?(\d{1,3})%',    re.DOTALL),
        ("black",   r'Black\(K\).*?(\d{1,3})%',   re.DOTALL),
    ]
    for col, pat, flag in patterns:
        m = re.search(pat, html, flag)
        if m:
            result[col] = int(m.group(1))

    if len(result) < 4:
        widths = re.findall(r'width:(\d+)%', html)
        if len(widths) >= 4:
            order = ["yellow", "magenta", "cyan", "black"]
            for i, col in enumerate(order):
                if col not in result:
                    try:
                        result[col] = int(widths[-(4 - i)])
                    except Exception:
                        log.debug("Toshiba scrape widths conversion failed for %s", ip, exc_info=True)

    if len(result) < 4:
        color_map = [
            ("yellow",  [r'Y(?:ellow)?.*?>(\d{1,3})<']),
            ("magenta", [r'M(?:agenta)?.*?>(\d{1,3})<']),
            ("cyan",    [r'C(?:yan)?.*?>(\d{1,3})<']),
            ("black",   [r'K(?:lack)?.*?>(\d{1,3})<']),
        ]
        for col, pats in color_map:
            if col not in result:
                for pat in pats:
                    m = re.search(pat, html, re.DOTALL)
                    if m:
                        val = int(m.group(1))
                        if 0 <= val <= 100:
                            result[col] = val
                            break

    if result and all(0 <= v <= 100 for v in result.values()):
        log.debug(f"Toshiba toner scrape {ip}: {result}")
        # ✅ باگ #10: ذخیره در کش
        _toner_scrape_cache[ip] = (time.time(), result)
        return result

    log.debug(f"Toshiba toner scrape {ip}: نتیجه‌ای یافت نشد")
    return None


def _walk_toner_remaining(ip: str, community: str, timeout: float = 2.0) -> dict:
    """
    روش سوم: SNMP Walk روی جدول مواد مصرفی برای یافتن درصد دقیق تونر
    OIDهای استفاده شده (Printer MIB):
    - 1.3.6.1.2.1.43.11.1.1.6 (prtMarkerSuppliesDescription) : نام کارتریج
    - 1.3.6.1.2.1.43.11.1.1.8 (prtMarkerSuppliesMaxCapacity) : ظرفیت
    - 1.3.6.1.2.1.43.11.1.1.9 (prtMarkerSuppliesRemaining) : باقی‌مانده
    """
    result = {}
    
    for idx in range(1, 11):  # حداکثر 10 ماده مصرفی
        try:
            # خواندن نام
            name_oid = f"1.3.6.1.2.1.43.11.1.1.6.1.{idx}"
            name = snmp_get_with_fallback(ip, name_oid, community, timeout=timeout)
            if name is None:
                continue  # این ایندکس وجود ندارد
            
            name_str = str(name).strip().lower()
            
            # تشخیص رنگ
            color = None
            if "black" in name_str or "bk" in name_str:
                color = "black"
            elif "cyan" in name_str:
                color = "cyan"
            elif "magenta" in name_str:
                color = "magenta"
            elif "yellow" in name_str:
                color = "yellow"
            else:
                continue  # ماده مصرفی غیر تونر (مثل درام)
            
            # خواندن ظرفیت
            max_oid = f"1.3.6.1.2.1.43.11.1.1.8.1.{idx}"
            max_val = snmp_get_with_fallback(ip, max_oid, community, timeout=timeout)
            
            # خواندن باقی‌مانده
            rem_oid = f"1.3.6.1.2.1.43.11.1.1.9.1.{idx}"
            rem_val = snmp_get_with_fallback(ip, rem_oid, community, timeout=timeout)
            
            if max_val is None or rem_val is None:
                _log_validation_error(ip, "walk_incomplete", 
                                     f"Toner {color} idx={idx}: max={max_val}, rem={rem_val}")
                continue
            
            try:
                max_int = int(max_val)
                rem_int = int(rem_val)
                
                if max_int > 0 and rem_int >= 0:
                    percent = round(rem_int / max_int * 100)
                    
                    # وضعیت
                    if percent == 0:
                        st = "empty"
                    elif percent <= 10:
                        st = "critical"
                    elif percent <= 25:
                        st = "low"
                    else:
                        st = "ok"
                    
                    result[color] = {
                        "level": percent,
                        "status": st,
                        "remaining": rem_int,
                        "max": max_int,
                        "source": "snmp_walk",
                    }
                    
                    log.debug(f"Toshiba walk {ip}: {color}={percent}% (rem={rem_int}, max={max_int})")
                    
            except (ValueError, TypeError) as e:
                _log_validation_error(ip, "walk_conversion", 
                                     f"Toner {color} idx={idx}: max={max_val}, rem={rem_val}, error={e}")
                
        except Exception as e:
            _log_validation_error(ip, "walk_exception", f"Toner idx={idx}: {e}")
    
    return result


def collect_toshiba(ip: str, name: str, community: str, start: float) -> dict:
    prev = store._prev.get(ip) or {}
    prev_a3 = prev.get("a3_total", 0)
    prev_a4 = prev.get("a4_total", 0)

    raw = snmp_get_bulk(ip, OIDS, community)
    elapsed = int((time.time() - start) * 1000)

    ut_raw = raw.get("uptime")
    ut = si(ut_raw)
    us = ut // 100
    uptime_str = f"{us // 86400}d {(us % 86400) // 3600:02d}:{(us % 3600) // 60:02d}"

    # ─── تونر با اولویت: TopAccess > Usage-based > SNMP Walk > NE_LEVEL ───
    
    # اولویت ۱: TopAccess Scrape
    scraped = _scrape_toshiba_toners(ip)
    
    # اولویت ۳ (fallback): SNMP Walk
    walk_result = None
    if not scraped:
        try:
            walk_result = _walk_toner_remaining(ip, community)
            if walk_result:
                log.info(f"Toshiba {ip}: SNMP walk successful for {len(walk_result)} toners")
        except Exception as e:
            _log_validation_error(ip, "walk_failed", str(e))
    
    toners = {}
    for col, ne_key in [("cyan","toner_cyan_status"),("magenta","toner_magenta_status"),
                        ("yellow","toner_yellow_status"),("black","toner_black_status")]:
        ne = si(raw.get(ne_key), 3)
        usage = si(raw.get(f"toner_{col}_usage"), 0)

        # اولویت ۱: TopAccess
        if scraped and col in scraped:
            level = scraped[col]
            st = ("ok" if level > 50 else "low" if level > 25 else
                  "critical" if level > 0 else "empty")
            source = "topaccess_scrape"
            
        # اولویت ۲: Usage-based estimation
        elif usage > 0:
            if col == "black":
                estimated_max = 40_000_000_000
            else:
                estimated_max = 20_000_000_000

            level = max(0, min(100, round(100 - (usage / estimated_max * 100))))
            
            # تصحیح بر اساس وضعیت NE
            if ne in (3, 4):
                level = max(level, 50)
            elif ne in (5, 6):
                level = max(level, 20)
            elif ne in (7, 9):
                level = max(level, 5)
            elif ne == 8:
                level = 0
                
            st = ("ok" if level > 50 else "low" if level > 25 else
                  "critical" if level > 0 else "empty")
            source = "usage_estimated"
            
        # اولویت ۳: SNMP Walk
        elif walk_result and col in walk_result:
            level = walk_result[col]["level"]
            st = walk_result[col]["status"]
            source = "snmp_walk"
            
        # اولویت ۴: NE_LEVEL
        else:
            if ne in NE_LEVEL:
                level = NE_LEVEL[ne]
                if level <= 0:
                    st = "empty"
                elif level <= 10:
                    st = "critical"
                elif level <= 25:
                    st = "low"
                else:
                    st = "ok"
            else:
                level = None
                st = TONER_STATUS.get(ne, "ok")
            source = "ne_flag_estimated"

        toners[col] = {
            "level": level,
            "status": st,
            "usage": usage,
            "usage_m": round(usage / 1_000_000, 2),
            "source": source,
        }

    trays = []
    for num, label in [(1,"Tray 1"),(2,"Tray 2"),(3,"Tray 3"),(6,"Bypass")]:
        lvl = si(raw.get(f"tray{num}_level"), -1)
        scode = si(raw.get(f"tray{num}_size"), 0)
        st = ("unknown" if lvl < 0 else "empty" if lvl == 0 else
              "low" if lvl <= 25 else "medium" if lvl <= 75 else "ok")
        trays.append({"name": label, "level": lvl,
                      "size": PAPER_SIZE_MAP.get(scode, f"#{scode}"), "status": st})

    alerts = []
    seen_codes = set()
    alert_priority = {5062: 0, 1104: 1, 808: 2, 1131: 3}
    for i in [1, 2, 3]:
        msg = ss(raw.get(f"alert{i}_msg"), "")
        code = si(raw.get(f"alert{i}_code"), 0)
        if msg and msg != "N/A" and code > 0 and code not in seen_codes:
            alerts.append({"message": msg, "code": code,
                           "priority": alert_priority.get(code, 99)})
            seen_codes.add(code)
    alerts = sorted(alerts, key=lambda a: a.get("priority", 99))
    alerts = [{"message": a["message"], "code": a["code"]} for a in alerts]

    total = si(raw.get("print_total"))
    
    # ═══ Retry برای total=0 ═══
    prev_total = prev.get("print_total") if prev else None
    if total == 0 and prev_total is not None and prev_total > 1000:
        log.warning(f"Toshiba {ip}: total=0 but prev={prev_total}, retrying...")
        retry_val = snmp_get_with_fallback(ip, OIDS["print_total"], community, timeout=5.0, version=1)
        retry_total = si(retry_val)
        if retry_total > 0:
            log.warning(f"Toshiba {ip}: retry successful → total={retry_total}")
            total = retry_total
        else:
            # ✅ باگ #10: ثبت خطا و نگهداری total=0 (نه prev_total)
            log.error(f"Toshiba {ip}: retry also failed, recording SNMP error")
            add_event(ip, "SNMP_ERROR", {
                "message": f"SNMP total=0 and retry failed for {ip}",
                "severity": "error",
                "prev_total": prev_total,
            })
            # total رو 0 نگه دار تا در poll بعدی دوباره تلاش بشه
            # اگر prev_total رو برگردونیم، چاپ‌های واقعی گم می‌شن

    color = si(raw.get("print_fc"))
    bw = si(raw.get("print_bw"))
    twin = si(raw.get("print_twin"))
    copy_fc = si(raw.get("print_copy_fc"))
    copy_bw = si(raw.get("print_copy_bw"))
    printer_fc = si(raw.get("print_printer_fc"))
    printer_bw = si(raw.get("print_printer_bw"))
    copy_ = copy_fc + copy_bw
    printer = printer_fc + printer_bw
    fax = si(raw.get("print_fax"))

    # نکته مهم: OID `twin` در بعضی مدل‌های Toshiba با تأخیر/دو مرحله update می‌شود.
    # اگر total را با twin دوباره اصلاح کنیم، ممکن است یک job دوبار در log ثبت شود.
    # بنابراین total خام دستگاه را منبع truth نگه می‌داریم و twin فقط برای نمایش نگه داشته می‌شود.
    twin_pages = twin * 2 if twin > 0 else 0
    bw_for_event = max(0, total - color) if total >= 0 and color >= 0 else bw

    a3_total = si(raw.get("a3_total"))
    a4_total = si(raw.get("a4_total"))
    delta_a3 = a3_total - prev_a3
    delta_a4 = a4_total - prev_a4

    paper_size = None
    if delta_a3 > 0 and delta_a4 == 0:
        paper_size = "Large (A3/B4)"
    elif delta_a4 > 0 and delta_a3 == 0:
        paper_size = "Small (A4/A5)"
    elif delta_a3 > 0 and delta_a4 > 0:
        paper_size = "Mixed"

    ps = {
        k: {
            "total": si(raw.get(f"{k}_total")),
            "fc": si(raw.get(f"{k}_fc")),
            "bw": si(raw.get(f"{k}_bw"))
        } for k in ["a4","a3","a4r","a5","b4"]
    }

    curr_codes = [a["code"] for a in alerts]
    black_level = None
    if toners.get("black", {}).get("level") is not None:
        black_level = toners["black"]["level"]
    else:
        for t in toners.values():
            if t.get("level") is not None:
                black_level = t["level"]
                break
    prev_toner = prev.get("toner_level")
    # ✅ باگ #11: پاس دادن a3_total و a4_total به _counters_event
    _counters_event(ip, total, prev, alerts, curr_codes,
                    full_color=color, black_white=bw_for_event, paper_size=paper_size,
                    current_toner_level=black_level, prev_toner_level=prev_toner,
                    uptime=ut, a3_total=a3_total, a4_total=a4_total,
                    poll_timestamp=datetime.fromtimestamp(start).isoformat())

    c_warns = validate_counter_consistency(
        {"total": total, "full_color": color, "black_white": bw,
         "copy": copy_, "printer": printer, "twin": twin,
         "copy_fc": copy_fc, "printer_fc": printer_fc}, "toshiba")
    for w in c_warns:
        log.warning(f"  {w}")

    log.info(f"  ✓ {name} [toshiba] total={total:,} fc={color:,} bw={bw:,} {elapsed}ms")

    # ═══ اصلاح: عدم بازنویسی PrevStore ═══
    with store._prev_lock:
        current_prev = store._prev.get(ip) or {}
        current_prev["a3_total"] = a3_total
        current_prev["a4_total"] = a4_total
        store._prev.set(ip, current_prev)

    return {
        "ip": ip, "name": name, "brand": "toshiba",
        "online": True, "last_poll": datetime.now().isoformat(), "poll_ms": elapsed,
        "device": {
            "model": ss(raw.get("model"), "TOSHIBA"),
            "serial": ss(raw.get("serial")),
            "firmware": ss(raw.get("firmware")),
            "uptime_str": uptime_str,
        },
        "counters": {
            "total": total, "full_color": color, "black_white": bw,
            "printer": printer, "printer_fc": printer_fc, "printer_bw": printer_bw,
            "copy": copy_, "copy_fc": copy_fc, "copy_bw": copy_bw,
            "twin": twin, "twin_pages": twin_pages, "fax": fax,
            "list": si(raw.get("print_list")),
            "scan_fc": si(raw.get("scan_fc")), "scan_bw": si(raw.get("scan_bw")),
            "scan_net_fc": si(raw.get("scan_net_fc")), "scan_net_bw": si(raw.get("scan_net_bw")),
        },
        "paper_sizes": ps, "trays": trays, "toners": toners, "alerts": alerts,
    }