"""
Endpoint های نمایش لاگ‌های امنیتی (فقط برای admin).
"""

from flask import Blueprint, jsonify, request, render_template

from web.auth import admin_required
from core.security_audit import get_recent_events, SecurityEvent

bp = Blueprint("security_audit", __name__)


@bp.route("/api/security/events", methods=["GET"])
@admin_required
def api_security_events():
    """
    لیست رویدادهای امنیتی اخیر (فقط admin).
    Query params:
      - limit: حداکثر تعداد (پیش‌فرض 100، حداکثر 1000)
      - event_type: فیلتر بر اساس نوع رویداد (failed_login، ...)
      - severity: فیلتر بر اساس شدت (info، warning، error، critical)
      - user_id: فقط رویدادهای یک کاربر
    """
    limit = min(int(request.args.get("limit", 100)), 1000)
    event_type = request.args.get("event_type")
    severity = request.args.get("severity")
    user_id = request.args.get("user_id", type=int)
    events = get_recent_events(
        limit=limit,
        event_type=event_type,
        severity=severity,
        user_id=user_id,
    )
    return jsonify({
        "events": events,
        "total": len(events),
        "available_types": [
            v for k, v in vars(SecurityEvent).items() if not k.startswith("_")
        ],
    })


@bp.route("/api/security/stats", methods=["GET"])
@admin_required
def api_security_stats():
    """آمار خلاصه رویدادهای امنیتی اخیر."""
    from core.security_audit import _db_conn
    try:
        from datetime import datetime, timedelta
        cutoff_24h = (datetime.now() - timedelta(hours=24)).isoformat()
        cutoff_7d = (datetime.now() - timedelta(days=7)).isoformat()

        with _db_conn() as conn:
            # تعداد failed login در ۲۴ ساعت گذشته
            failed_24h = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE event_type=? AND timestamp>=?",
                (SecurityEvent.FAILED_LOGIN, cutoff_24h),
            ).fetchone()[0]
            # تعداد successful login در ۲۴ ساعت
            success_24h = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE event_type=? AND timestamp>=?",
                (SecurityEvent.SUCCESSFUL_LOGIN, cutoff_24h),
            ).fetchone()[0]
            # IPهای پرتکرار با failed login (top 10) در ۷ روز
            top_ips = conn.execute(
                '''SELECT ip_address, COUNT(*) as cnt FROM security_events
                   WHERE event_type=? AND timestamp>=? AND ip_address IS NOT NULL
                   GROUP BY ip_address ORDER BY cnt DESC LIMIT 10''',
                (SecurityEvent.FAILED_LOGIN, cutoff_7d),
            ).fetchall()
            # رویدادهای critical در ۷ روز
            critical_7d = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE severity='critical' AND timestamp>=?",
                (cutoff_7d,),
            ).fetchone()[0]
        # Total events and warnings in 7 days
        total_7d = conn.execute(
            "SELECT COUNT(*) FROM security_events WHERE timestamp>=?",
            (cutoff_7d,),
        ).fetchone()[0]
        warnings_7d = conn.execute(
            "SELECT COUNT(*) FROM security_events WHERE severity IN ('warning','critical') AND timestamp>=?",
            (cutoff_7d,),
        ).fetchone()[0]
        return jsonify({
            "failed_logins_24h": failed_24h,
            "successful_logins_24h": success_24h,
            "critical_events_7d": critical_7d,
            "total_events_7d": total_7d,
            "warnings_7d": warnings_7d,
            "top_failed_ips_7d": [{"ip": r[0], "count": r[1]} for r in top_ips],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/security", methods=["GET"])
@admin_required
def security_page():
    """صفحه امنیت"""
    return render_template("security.html", load_dashboard_scripts=True)
