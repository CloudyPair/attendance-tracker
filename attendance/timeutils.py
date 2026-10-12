"""Границы суток в часовом поясе проекта (settings.TIME_ZONE).

Правила «отмечать до 00:00 следующего дня» и «замена до конца дня» считаются
по местному времени, а БД хранит UTC - поэтому перед расчётом переводим в местное.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone


def _local(moment: datetime) -> datetime:
    return timezone.localtime(moment) if timezone.is_aware(moment) else moment


def day_start(moment: datetime) -> datetime:
    """00:00 того же дня."""
    local = _local(moment)
    return datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)


def next_midnight(moment: datetime) -> datetime:
    """00:00 следующего дня."""
    local = _local(moment)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=local.tzinfo)
