import urllib
import requests
import bs4
import json

cfSession = requests.sessions.Session()
cfSession.headers = {
    'Host': 'codeforces.com',
    'user-agent': r'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.83 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'X-MicrosoftAjax': 'Delta=true',
    'Cache-Control': 'max-age=0',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept': r'*/*',
    'Accept-Encoding': 'gzip, deflate, br'
}
cfCookies = requests.cookies.RequestsCookieJar()
cfSession.cookies = cfCookies
