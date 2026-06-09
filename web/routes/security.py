"""
Endpoint های نمایش لاگ‌های امنیتی (فقط برای admin).
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, render_template

from web.auth import admin_required
from core.security_audit import get_recent_events, SecurityEvent, _db_conn

bp = Blueprint("security_audit", __name__)


@bp.route("/api/security/events", methods=["GET"])
@admin_required
def api_security_events():
    """
    لیست رویدادهای امنیتی اخیر (فقط admin).
    Query params:
      - limit: حداکثر تعداد (پیش‌فرض 100، حداکثر 1000)
      - event_type: فیلتر بر اساس نوع رویداد (failed_login، ...)
      - severity: فیلتر بر اساس شدت (info، warning، critical)
      - user_id: فقط رویدادهای یک کاربر
    """
    limit = request.args.get("limit", type=int) or 100
    limit = max(1, min(limit, 1000))
    event_type = request.args.get("event_type") or None
    severity = request.args.get("severity") or None
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
        "available_types": [event.value for event in SecurityEvent],
    })


@bp.route("/api/security/stats", methods=["GET"])
@admin_required
def api_security_stats():
    """آمار خلاصه رویدادهای امنیتی اخیر."""
    try:
        cutoff_24h = (datetime.now() - timedelta(hours=24)).isoformat()
        cutoff_7d = (datetime.now() - timedelta(days=7)).isoformat()

        with _db_conn() as conn:
            failed_24h = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE event_type=? AND timestamp>=?",
                (SecurityEvent.FAILED_LOGIN.value, cutoff_24h),
            ).fetchone()[0]

            success_24h = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE event_type=? AND timestamp>=?",
                (SecurityEvent.SUCCESSFUL_LOGIN.value, cutoff_24h),
            ).fetchone()[0]

            top_ips = conn.execute(
                '''SELECT ip_address, COUNT(*) as cnt FROM security_events
                   WHERE event_type=? AND timestamp>=? AND ip_address IS NOT NULL
                   GROUP BY ip_address ORDER BY cnt DESC LIMIT 10''',
                (SecurityEvent.FAILED_LOGIN.value, cutoff_7d),
            ).fetchall()

            critical_7d = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE severity='critical' AND timestamp>=?",
                (cutoff_7d,),
            ).fetchone()[0]

            total_7d = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE timestamp>=?",
                (cutoff_7d,),
            ).fetchone()[0]

            warnings_7d = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE severity IN ('warning','critical') AND timestamp>=?",
                (cutoff_7d,),
            ).fetchone()[0]

        return jsonify({
            "failed_logins_24h": int(failed_24h or 0),
            "successful_logins_24h": int(success_24h or 0),
            "critical_events_7d": int(critical_7d or 0),
            "total_events_7d": int(total_7d or 0),
            "warnings_7d": int(warnings_7d or 0),
            "top_failed_ips_7d": [{"ip": row[0], "count": int(row[1] or 0)} for row in top_ips],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/security", methods=["GET"])
@admin_required
def security_page():
    """صفحه امنیت"""
    return render_template("security.html", load_dashboard_scripts=False)
