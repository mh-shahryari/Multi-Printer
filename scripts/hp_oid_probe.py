import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.snmp.protocol import snmp_get_with_fallback

ips = ["172.16.25.38", "172.16.0.45"]
oids = [
    # PRT-MIB supply table first entries
    "1.3.6.1.2.1.43.11.1.1.6.1.1",  # name idx1
    "1.3.6.1.2.1.43.11.1.1.8.1.1",  # max idx1
    "1.3.6.1.2.1.43.11.1.1.9.1.1",  # rem idx1
    # some other supply indices
    "1.3.6.1.2.1.43.11.1.1.6.1.2",
    "1.3.6.1.2.1.43.11.1.1.8.1.2",
    "1.3.6.1.2.1.43.11.1.1.9.1.2",
    # HP enterprise candidate OIDs
    "1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.1.5.5.1.1",
    "1.3.6.1.4.1.11.2.3.9.1.1.7.0",
    "1.3.6.1.4.1.11.2.3.9.4.2.1.4.1.2.4.1.2.1.5.5.1.1",
    # sysDescr and sysObjectID
    "1.3.6.1.2.1.1.1.0",
    "1.3.6.1.2.1.1.2.0",
]
for ip in ips:
    print(f"--- {ip} ---")
    for oid in oids:
        try:
            val = snmp_get_with_fallback(ip, oid, "public", timeout=2.0)
            print(f"{oid} -> {val}")
        except Exception as e:
            print(f"{oid} -> ERROR {e}")
    print()
