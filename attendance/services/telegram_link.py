"""Привязка Telegram одноразовой ссылкой (sequence_telegram_link.puml)."""
from datetime import timedelta

from attendance.models import Student, TelegramLink

from .interfaces import IClock

LINK_TOKEN_TTL = timedelta(minutes=15)


class TelegramLinkService:
    def __init__(self, clock: IClock):
        self.clock = clock

    def create_link_token(self, student: Student) -> str:
        """1. token = secrets.token_urlsafe(32).
        2. INSERT LinkToken(expires_at = now + LINK_TOKEN_TTL).
        3. Вернуть token (сайт строит ссылку t.me/<bot>?start=<token>).
        """
        raise NotImplementedError("ЛР4")

    def bind(self, token: str, chat_id: str) -> TelegramLink:
        """1. Найти LinkToken; нет или not is_valid(now) -> InvalidChangeError.
        2. В транзакции: создать/обновить TelegramLink(chat_id), LinkToken.used_at = now.
        """
        raise NotImplementedError("ЛР4")
