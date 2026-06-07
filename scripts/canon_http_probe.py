import re
import requests

ip = '172.16.25.39'
urls = [
    f'http://{ip}/',
    f'http://{ip}/Status.html',
    f'http://{ip}/index.html',
    f'http://{ip}/cgi-bin/maincgi.cgi',
    f'http://{ip}/cgi-bin/StatusConsole',
    f'http://{ip}/status.html',
]
for url in urls:
    try:
        r = requests.get(url, timeout=4, headers={'User-Agent': 'Mozilla/5.0'})
        print('URL', url, 'status', r.status_code, 'len', len(r.text))
        txt = r.text
        for pat in [r'Cartridge\s*137.{0,120}?', r'(\d{1,3})\s*%', r'Ink|Toner|Supply']:
            m = re.search(pat, txt, re.I | re.S)
            if m:
                s = m.group(0)
                print('MATCH', pat, '=>', s[:200].replace('\n',' '))
        print('---')
    except Exception as e:
        print('URL', url, 'ERR', e)
