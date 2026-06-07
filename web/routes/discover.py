import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, jsonify, request
from core.snmp.protocol import snmp_get

bp = Blueprint("discover", __name__)
log = logging.getLogger("PrinterMonitor")

PRIMARY_OID = "1.3.6.1.2.1.1.1.0"  # sysDescr

SECONDARY_OIDS = [
    "1.3.6.1.4.1.1129.2.3.50.1.2.3.1.3.1.1",       # Toshiba
    "1.3.6.1.4.1.11.2.3.9.1.1.3.1.1.1.1.2.0",       # HP
    "1.3.6.1.4.1.1602.1.1.1.1.0",                     # Canon
    "1.3.6.1.4.1.2435.2.3.9.1.1.3.1.1.1.1.2.0",     # Brother
]

FALLBACK_COMMUNITIES = ["public", "private", "TOSHIBA", "toshiba"]


def _try_snmp(ip, oid, comm, timeout=0.5):
    """تلاش با v2c، در صورت شکست و فقط برای PRIMARY_OID با v1 مجدد تلاش کن"""
    # 1. ابتدا v2c
    val = snmp_get(ip, oid, comm, timeout=timeout, version=2)
    if val and str(val) not in ("N/A", "None", ""):
        return val, "v2c"

    # 2. در صورت عدم پاسخ و فقط برای OID اصلی، fallback به v1
    if oid == PRIMARY_OID:
        val = snmp_get(ip, oid, comm, timeout=timeout, version=1)
        if val and str(val) not in ("N/A", "None", ""):
            return val, "v1"

    return None, None


@bp.route('/api/printers/discover', methods=['POST'])
def api_discover():
    body      = request.get_json() or {}
    community = body.get("community", "public")
    ranges    = body.get("ranges")
    if ranges is None:
        subnet = body.get("subnet", "172.16.25")
        s_i    = int(body.get("start", 1))
        e_i    = int(body.get("end", 254))
        ranges = [{"subnet": subnet, "start": s_i, "end": e_i}]

    found = []
    lock  = threading.Lock()

    def probe(ip):
        communities = [community] + [c for c in FALLBACK_COMMUNITIES if c != community]

        for comm in communities:
            val, ver = _try_snmp(ip, PRIMARY_OID, comm, timeout=0.5)
            if val:
                log.info(f"  ✔ Discovery: {ip} پاسخ داد ({ver}, community='{comm}')")
                with lock:
                    found.append({
                        "ip": ip,
                        "model": str(val)[:50],
                        "community": comm,
                        "snmp_version": ver
                    })
                return

        # مرحله ۲: OIDهای اختصاصی برند (فقط v2c)
        for oid in SECONDARY_OIDS:
            val = snmp_get(ip, oid, community, timeout=0.5, version=2)
            if val and str(val) not in ("N/A", "None", ""):
                log.info(f"  ✔ Discovery: {ip} پاسخ داد (v2c, brand-specific OID)")
                with lock:
                    found.append({
                        "ip": ip,
                        "model": str(val)[:50],
                        "community": community,
                        "snmp_version": "v2c"
                    })
                return

    all_ips = []
    for rng in ranges:
        subnet = rng["subnet"]
        s, e   = int(rng["start"]), int(rng["end"])
        for i in range(s, e + 1):
            all_ips.append(f"{subnet}.{i}")

    with ThreadPoolExecutor(max_workers=100) as ex:
        for _ in as_completed([ex.submit(probe, ip) for ip in all_ips]):
            pass

    return jsonify({"found": found, "scanned": len(all_ips)})