"""Разовый импорт расписания из .ics (sequence_schedule_import.puml).

Вызывать будет management-команда `manage.py import_schedule <группа> <файл.ics>`.
"""
from dataclasses import dataclass, field
from typing import BinaryIO


@dataclass(frozen=True, kw_only=True)
class ImportResult:
    created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class ScheduleImporter:
    def import_ics(self, file: BinaryIO, group_id: int) -> ImportResult:
        """1. У группы уже есть занятия -> отказ (импорт разовый).
        2. Разобрать календарь (библиотека icalendar), развернуть повторения.
        3. В одной транзакции: пропустить служебные события; найти/создать Subject,
           Teacher, Course; INSERT Lesson(external_uid = UID + дата вхождения).
        4. Любая ошибка разбора -> откат, ImportResult с ошибками.
        """
        raise NotImplementedError("ЛР4")

    def _expand_recurrence(self, vevent) -> list:
        raise NotImplementedError("ЛР4")

    def _is_service_event(self, vevent) -> bool:
        raise NotImplementedError("ЛР4")

    def _parse_occurrence(self, vevent) -> dict:
        raise NotImplementedError("ЛР4")
