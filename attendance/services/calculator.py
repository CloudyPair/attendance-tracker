"""Расчёт посещаемости, порога и иконки (UML/activity_threshold.puml).

Чистые функции: в БД не ходят, принимают числа или уже загруженные объекты.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from attendance.models import AttendanceRecord, AttendanceStatus, Lesson


class WarningLevel(Enum):
    OK = "OK"
    WARNING = "WARNING"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


@dataclass(frozen=True, kw_only=True)
class AttendanceStats:
    total: int = 0
    marked: int = 0
    present: int = 0
    missed: int = 0
    not_marked: int = 0
    percent: int = 100
    allowed_misses: int = 0
    level: WarningLevel = WarningLevel.OK


class AttendanceCalculator:
    @staticmethod
    def current_percent(marked: int, missed: int) -> int:
        if marked < 0 or missed < 0 or missed > marked:
            raise ValueError("Пропусков не может быть больше отмеченных занятий")
        if marked == 0:
            return 100
        return (marked - missed) * 100 // marked

    @staticmethod
    def allowed_misses(total: int, missed: int, threshold_percent: int) -> int:
        """floor(всего_занятий × (1 − порог)) − уже_пропущено."""
        if not 0 <= threshold_percent <= 100:
            raise ValueError("Порог должен быть в диапазоне 0..100")
        return total * (100 - threshold_percent) // 100 - missed

    @staticmethod
    def get_level(allowed_misses: int) -> WarningLevel:
        if allowed_misses < 0:
            return WarningLevel.BELOW_THRESHOLD
        if allowed_misses <= 1:
            return WarningLevel.WARNING
        return WarningLevel.OK

    @staticmethod
    def get_icon(level: WarningLevel) -> str:
        return {WarningLevel.OK: "",
                WarningLevel.WARNING: "⚠️",
                WarningLevel.BELOW_THRESHOLD: "❌"}[level]

    @staticmethod
    def calculate(lessons: list[Lesson], records: list[AttendanceRecord],
                  threshold_percent: int, now: datetime) -> AttendanceStats:
        """Статистика одного студента.

        lessons - все занятия курса за период (в т.ч. будущие: от них зависит total);
        records - записи этого студента (лишние, не из lessons, игнорируются).
        """
        own = {l.pk for l in lessons}
        counted = [r for r in records
                   if r.lesson_id in own and r.status != AttendanceStatus.NOT_MARKED]
        present = sum(1 for r in counted if r.status == AttendanceStatus.PRESENT)
        missed = sum(1 for r in counted if r.status == AttendanceStatus.ABSENT)
        marked_lessons = {r.lesson_id for r in counted}
        not_marked = sum(1 for l in lessons if l.has_started(now) and l.pk not in marked_lessons)
        total = len(lessons)
        allowed = AttendanceCalculator.allowed_misses(total, missed, threshold_percent)
        return AttendanceStats(
            total=total, marked=present + missed, present=present, missed=missed,
            not_marked=not_marked,
            percent=AttendanceCalculator.current_percent(present + missed, missed),
            allowed_misses=allowed, level=AttendanceCalculator.get_level(allowed))
