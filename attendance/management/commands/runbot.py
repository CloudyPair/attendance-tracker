"""Запуск отдельного процесса Telegram-бота и обработчика уведомлений."""
import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from attendance.telegram_bot import run_bot


class Command(BaseCommand):
    help = "Telegram-бот ФЛАГ (polling) и очередь уведомлений"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Добавьте TELEGRAM_BOT_TOKEN в локальный .env")
        # В сетевых исключениях библиотек могут встречаться адреса с токеном.
        logging.getLogger("aiogram").setLevel(logging.CRITICAL)
        logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
        self.stdout.write("Запуск Telegram-бота. Остановка: Ctrl+C.")
        try:
            asyncio.run(run_bot(on_ready=lambda: self.stdout.write("Бот подключен. Polling запущен.")))
        except KeyboardInterrupt:
            pass
        except Exception as error:
            raise CommandError("Бот остановлен. Проверьте токен, интернет и отсутствие второго процесса runbot. "
                               f"Тип ошибки: {type(error).__name__}") from None
