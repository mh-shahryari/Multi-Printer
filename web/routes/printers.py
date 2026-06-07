import threading
import logging
from flask import Blueprint, jsonify, request
from flask_login import current_user
from core import store
from core.database import add_event, save_printer_counters
from core.poller import collect, poll_one
from core.oid.scanner import scan_printer_oids
from config.settings import POLL_INTERVAL
from web.auth import user_can_access_office, allowed_printer_ips, user_allowed_offices

log = logging.getLogger("PrinterMonitor")

bp = Blueprint("printers", __name__)


@bp.route('/api/printers')
def api_printers():
    allowed_offices = user_allowed_offices(current_user)
    allowed_ips = allowed_printer_ips(current_user)
    with store.data_lock:
        snap = list(store.printer_data.values())
    with store.printers_lock:
        cfg = list(store.PRINTERS)
    if allowed_offices:
        snap = [d for d in snap if d.get("ip") in allowed_ips]
        cfg = [p for p in cfg if p.get("ip") in allowed_ips]
    seen = {d["ip"] for d in snap}
    for p in cfg:
        if p["ip"] not in seen:
            snap.append({
                "ip": p["ip"], "name": p["name"], "nickname": p.get("nickname", ""),
                "online": None, "last_poll": None
            })
    return jsonify({"printers": snap, "meta": {
        "total": len(cfg),
        "online": sum(1 for d in snap if d.get("online")),
        "offline": sum(1 for d in snap if d.get("online") is False),
        "poll_count": store.poll_stats["count"],
        "last_poll": store.poll_stats["last"],
        "poll_interval": POLL_INTERVAL,
    }})


@bp.route('/api/printer/<path:ip>')
def api_printer(ip):
    if not user_can_access_office(current_user, ip):
        return jsonify({"error": "forbidden"}), 403
    with store.data_lock:
        d = store.printer_data.get(ip)
    return jsonify(d) if d else (jsonify({"error": "not found"}), 404)


@bp.route('/api/debug/printer/<path:ip>')
def debug_printer(ip):
    if not user_can_access_office(current_user, ip):
        return jsonify({"error": "forbidden"}), 403
    with store.data_lock:
        data = store.printer_data.get(ip)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@bp.route('/api/printers/add', methods=['POST'])
def api_add():
    body = request.get_json() or {}
    ip = (body.get("ip") or "").strip()
    name = (body.get("name") or f"Printer {ip}").strip()
    community = (body.get("community") or "public").strip()
    nickname = (body.get("nickname") or "").strip()
    if not ip:
        return jsonify({"error": "IP required"}), 400
    with store.printers_lock:
        if any(p["ip"] == ip for p in store.PRINTERS):
            return jsonify({"error": "already exists"}), 409
        store.PRINTERS.append({"ip": ip, "name": name, "community": community, "nickname": nickname})
        store.save_printers(store.PRINTERS)
    threading.Thread(
        target=lambda: poll_one({"ip": ip, "name": name, "community": community, "nickname": nickname}),
        daemon=True
    ).start()
    return jsonify({"status": "added", "ip": ip, "name": name})


@bp.route('/api/printers/bulk-add', methods=['POST'])
def api_bulk_add():
    body = request.get_json() or {}
    items = body.get("printers", [])
    do_scan = body.get("scan", True)
    skip_exist = body.get("skip_existing", True)

    if not items or not isinstance(items, list):
        return jsonify({"error": "آرایه printers الزامی است"}), 400
    if len(items) > 50:
        return jsonify({"error": "حداکثر ۵۰ پرینتر در هر درخواست"}), 400

    from core.store import _normalize_printer
    added, skipped, failed = [], [], []

    for raw in items:
        if not isinstance(raw, dict):
            failed.append({"item": raw, "reason": "فرمت نامعتبر"})
            continue
        p = _normalize_printer(raw)
        ip = p["ip"]
        if not ip:
            failed.append({"item": raw, "reason": "IP خالی است"})
            continue
        with store.printers_lock:
            exists = any(x["ip"] == ip for x in store.PRINTERS)
        if exists:
            (skipped if skip_exist else failed).append({"ip": ip, "reason": "قبلاً وجود دارد"})
            continue
        with store.printers_lock:
            store.PRINTERS.append(p)
            store.save_printers(store.PRINTERS)
        added.append(p)

    if added:
        def _bg_init(new_printers):
            for p in new_printers:
                try:
                    if do_scan:
                        profile = scan_printer_oids(p["ip"], p.get("community", "public"))
                        if not p.get("brand") and profile and profile.get("brand", "unknown") != "unknown":
                            p["brand"] = profile["brand"]
                            with store.printers_lock:
                                for i, x in enumerate(store.PRINTERS):
                                    if x["ip"] == p["ip"]:
                                        store.PRINTERS[i] = _normalize_printer(p)
                                store.save_printers(store.PRINTERS)
                            # بعد از به‌روزرسانی برند در PRINTERS، بلافاصله poll_one بگیر تا printer_data بروز شود
                            poll_one(p)
                        else:
                            # اگر برند قبلاً مشخص بود یا اسکن نشد، باز هم یک poll اولیه انجام بده
                            result = collect(p)
                            with store.data_lock:
                                store.printer_data[p["ip"]] = result
                    else:
                        result = collect(p)
                        with store.data_lock:
                            store.printer_data[p["ip"]] = result
                except Exception as e:
                    log.exception("bulk-add init %s failed", p['ip'])
        threading.Thread(target=_bg_init, args=(list(added),), daemon=True).start()

    return jsonify({
        "total_added": len(added),
        "added": added,
        "skipped": skipped,
        "failed": failed,
    }), (200 if added or skipped else 400)


@bp.route('/api/printers/remove', methods=['POST'])
def api_remove():
    ip = (request.get_json() or {}).get("ip", "").strip()
    with store.printers_lock:
        before = len(store.PRINTERS)
        store.PRINTERS[:] = [p for p in store.PRINTERS if p["ip"] != ip]
        if len(store.PRINTERS) == before:
            return jsonify({"error": "not found"}), 404
        store.save_printers(store.PRINTERS)
    with store.data_lock:
        store.printer_data.pop(ip, None)
    return jsonify({"status": "removed", "ip": ip})


@bp.route('/api/discover/auto-add', methods=['POST'])
def api_auto_add_printer():
    data = request.json or {}
    ip = data.get("ip", "").strip()
    community = data.get("community", "public")
    custom_name = data.get("name", "").strip()
    if not ip:
        return jsonify({"error": "ip الزامی است"}), 400
    with store.printers_lock:
        if any(p["ip"] == ip for p in store.PRINTERS):
            return jsonify({"error": f"{ip} قبلاً اضافه شده"}), 409
    try:
        profile = scan_printer_oids(ip, community, force=False)
        if not profile:
            return jsonify({"error": f"پرینتر {ip} پاسخ نداد"}), 404
        s = profile["summary"]
        name = custom_name or f"{s['brand'].upper()} {s['model']}"
        new_printer = {"ip": ip, "name": name, "community": community, "brand": s["brand"], "nickname": ""}
        with store.printers_lock:
            store.PRINTERS.append(new_printer)
            store.save_printers(store.PRINTERS)

        def _poll_new():
            result = collect(new_printer)
            with store.data_lock:
                store.printer_data[new_printer["ip"]] = result
        threading.Thread(target=_poll_new, daemon=True).start()
        return jsonify({"status": "added", "printer": new_printer, "summary": s})
    except Exception as e:
        log.exception("auto-add printer %s failed", ip)
        return jsonify({"error": str(e)}), 500


@bp.route('/api/printer/<path:ip>/rename', methods=['POST'])
def rename_printer(ip):
    data = request.get_json() or {}
    new_nickname = data.get("nickname", "").strip()
    with store.printers_lock:
        for p in store.PRINTERS:
            if p["ip"] == ip:
                p["nickname"] = new_nickname
                store.save_printers(store.PRINTERS)
                with store.data_lock:
                    if ip in store.printer_data:
                        store.printer_data[ip]["nickname"] = new_nickname
                return jsonify({"status": "ok", "nickname": new_nickname})
    return jsonify({"error": "printer not found"}), 404


@bp.route('/api/printer/<path:ip>/toner_reset', methods=['POST'])
def toner_reset(ip):
    try:
        if not user_can_access_office(current_user, ip):
            return jsonify({"error": "forbidden"}), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid JSON body"}), 400

        color = (data.get('color') or '').strip().lower()
        if not color:
            return jsonify({"error": "color required"}), 400

        if color not in ('black', 'cyan', 'magenta', 'yellow'):
            return jsonify({"error": "invalid color"}), 400

        try:
            new_level = int(data.get('new_level', 100))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid new_level"}), 400

        if new_level < 0 or new_level > 100:
            return jsonify({"error": "new_level must be between 0 and 100"}), 400

        with store.data_lock:
            printer = store.printer_data.get(ip)
            if printer is None:
                return jsonify({"error": "printer not found"}), 404
            toners = printer.get('toners')
            if not isinstance(toners, dict) or color not in toners:
                return jsonify({"error": "color not available"}), 400
            toners[color]['level'] = new_level
            if new_level == 0:
                status = 'empty'
            elif new_level <= 5:
                status = 'critical'
            elif new_level <= 15:
                status = 'low'
            else:
                status = 'ok'
            toners[color]['status'] = status

        prev = store._prev.get(ip) or {}
        new_prev = {
            'print_total': prev.get('print_total'),
            'full_color': prev.get('full_color'),
            'black_white': prev.get('black_white'),
            'toner_level': new_level,
            'manual_override': 1,
            'override_color': color,
            'override_base_level': new_level,
            'override_start_total': printer.get('counters', {}).get('total', 0) if isinstance(printer.get('counters'), dict) else 0,
            'override_start_toner': new_level,
            'yield_per_page': prev.get('yield_per_page', 2000),
            'alert_codes': prev.get('alert_codes', []),
            'last_alert_codes': prev.get('last_alert_codes', []),
            'uptime': prev.get('uptime'),
        }
        store._prev.set(ip, new_prev)
        save_printer_counters(ip, store._prev.get(ip))

        username = current_user.username if current_user.is_authenticated else 'سیستم'
        add_event(ip, 'REFILL', {
            'message': f'تنظیم دستی: کارتریج {color} به {new_level}% تنظیم شد',
            'severity': 'info',
            'username': username,
            'manual_reset': True,
            'auto_detected': False,
        })

        return jsonify({'status': 'ok'})
    except Exception as e:
        log.exception('toner_reset failed for %s', ip)
        return jsonify({"error": "internal server error"}), 500