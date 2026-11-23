"""Проверка WSGI через локальный HTTP без обращения к внешнему домену."""
from urllib.request import Request, urlopen

request = Request("http://127.0.0.1:8000/login/",
                  headers={"Host": "localhost", "X-Forwarded-Proto": "https"})
with urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise SystemExit(1)
