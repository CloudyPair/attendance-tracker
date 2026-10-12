from datetime import datetime

from django.utils import timezone

from .interfaces import IClock


class DjangoClock(IClock):
    """Текущее время в часовом поясе проекта (settings.TIME_ZONE)."""

    def now(self) -> datetime:
        return timezone.localtime()
