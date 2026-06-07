import requests, re
ip='172.16.25.39'
html=requests.get(f'http://{ip}/', timeout=4, headers={'User-Agent':'Mozilla/5.0'}).text
print(html)
