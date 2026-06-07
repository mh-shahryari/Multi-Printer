import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.snmp.protocol import snmp_get_with_fallback

ips = ["172.16.25.38","172.16.0.45"]
for ip in ips:
    print('---', ip)
    for idx in range(1, 11):
        name_oid = f"1.3.6.1.2.1.43.11.1.1.6.1.{idx}"
        max_oid  = f"1.3.6.1.2.1.43.11.1.1.8.1.{idx}"
        rem_oid  = f"1.3.6.1.2.1.43.11.1.1.9.1.{idx}"
        n = snmp_get_with_fallback(ip, name_oid, 'public', timeout=1.5)
        m = snmp_get_with_fallback(ip, max_oid, 'public', timeout=1.5)
        r = snmp_get_with_fallback(ip, rem_oid, 'public', timeout=1.5)
        print(idx, 'name->', n, 'max->', m, 'rem->', r)
    print()
