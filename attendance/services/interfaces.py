"""Интерфейсы внешних зависимостей ядра: часы, канал уведомлений, экспорт.

Через них сервисы не зависят от конкретной реализации, а в тестах их можно подменить.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .reports import CourseReport


class IClock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class INotificationChannel(ABC):
    @abstractmethod
    def send(self, chat_id: str, text: str) -> bool:
        raise NotImplementedError


class IReportExporter(ABC):
    @property
    @abstractmethod
    def format(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def export(self, report: CourseReport) -> bytes:
        raise NotImplementedError
