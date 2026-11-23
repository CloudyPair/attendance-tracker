"""Синхронный адаптер Bot API для уведомлений из Django."""
import json
from urllib.request import Request, urlopen

from django.conf import settings

from .interfaces import INotificationChannel


class TelegramChannel(INotificationChannel):
    def send(self, chat_id: str, text: str) -> bool:
        if not settings.TELEGRAM_BOT_TOKEN:
            return False
        payload = json.dumps({"chat_id": chat_id, "text": text.translate(
            str.maketrans({"ё": "е", "Ё": "Е", "·": None}))[:4096]}, ensure_ascii=False).encode("utf-8")
        request = Request(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                          data=payload, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                return bool(json.load(response).get("ok"))
        except Exception:
            return False
