import sqlite3
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from config.settings import DB_PATH

bp = Blueprint("stats", __name__)
log = logging.getLogger("PrinterMonitor")


@bp.route('/api/stats/daily')
def api_daily_stats():
    ip = request.args.get('ip')
    days = min(request.args.get('days', default=30, type=int), 365)
    start_date = (datetime.now() - timedelta(days=days)).date().isoformat()

    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        c = conn.cursor()

        # استفاده از substr به جای strftime برای اطمینان از کار با timestamp TEXT با فرمت ISO
        if ip:
            c.execute('''
                SELECT substr(timestamp, 1, 10) as day, COALESCE(SUM(pages), 0) as total
                FROM logs
                WHERE printer_ip = ? AND type = 'PRINT' AND timestamp >= ?
                  AND pages IS NOT NULL AND pages > 0
                GROUP BY day ORDER BY day
            ''', (ip, start_date))
        else:
            c.execute('''
                SELECT substr(timestamp, 1, 10) as day, COALESCE(SUM(pages), 0) as total
                FROM logs
                WHERE type = 'PRINT' AND timestamp >= ?
                  AND pages IS NOT NULL AND pages > 0
                GROUP BY day ORDER BY day
            ''', (start_date,))

        rows = c.fetchall()
        conn.close()

        date_dict = {row[0]: row[1] for row in rows}
        start_dt = datetime.now().date() - timedelta(days=days)
        all_dates = []
        all_totals = []
        for i in range(days + 1):
            d = (start_dt + timedelta(days=i)).isoformat()
            all_dates.append(d)
            all_totals.append(date_dict.get(d, 0))

        return jsonify({
            "dates": all_dates,
            "totals": all_totals,
            "printer_ip": ip,
            "days": days
        })
    except Exception as e:
        log.error(f"Stats API error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500