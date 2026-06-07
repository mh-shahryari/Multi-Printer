import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ips = ["172.16.25.38","172.16.0.45"]
paths = ['/', '/index.html', '/hp/device', '/hp/device/this.LCRequests', '/hp/device/ink_levels', '/hp/device/supplies', '/supplies', '/hp/device/InternalPages/Supplies']

for ip in ips:
    found = None
    print('---', ip)
    for p in paths:
        url = f'http://{ip}{p}'
        try:
            req = Request(url, headers={'User-Agent':'curl/7.64'})
            with urlopen(req, timeout=2) as r:
                txt = r.read(50000).decode('utf-8', errors='ignore')
                # search for percentage
                m = re.search(r'([0-9]{1,3})\s*%|([0-9]{1,3})\s+percent|level[^0-9]{0,10}([0-9]{1,3})', txt, re.I)
                if m:
                    for g in m.groups():
                        if g:
                            val = int(g)
                            if 0 <= val <= 100:
                                found = (p, val)
                                break
                if found:
                    print('SCRAPE', url, '->', found[1])
                    break
        except (URLError, HTTPError, Exception) as e:
            # ignore
            pass
    if not found:
        print('No supply level found via HTTP')
    print()
