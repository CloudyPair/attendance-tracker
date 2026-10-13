"""Расчёт посещаемости, порога и иконки (UML/activity_threshold.puml).

Функции не обращаются к БД: получают числа или уже загруженные объекты,
поэтому их можно тестировать без Django.
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
    total: int = 0           # все занятия курса за период, включая будущие
    marked: int = 0          # отмеченные: present + missed
    present: int = 0
    missed: int = 0
    not_marked: int = 0      # начавшиеся занятия без отметки
    percent: int = 100
    allowed_misses: int = 0  # сколько ещё можно пропустить
    level: WarningLevel = WarningLevel.OK


class AttendanceCalculator:
    @staticmethod
    def current_percent(marked: int, missed: int) -> int:
        """Процент посещений среди отмеченных занятий."""
        if marked < 0 or missed < 0 or missed > marked:
            raise ValueError("Пропусков не может быть больше отмеченных занятий")
        if marked == 0:
            return 100
        return (marked - missed) * 100 // marked

    @staticmethod
    def allowed_misses(total: int, missed: int, threshold_percent: int) -> int:
        """allowed = floor(total × (100 − порог) / 100) − missed.

        Пример: 10 занятий, порог 50 % - всего можно пропустить 5;
        если уже пропущено 3, допустимо ещё 2.
        """
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
        if level == WarningLevel.BELOW_THRESHOLD:
            return "❌"
        if level == WarningLevel.WARNING:
            return "⚠️"
        return ""

    @staticmethod
    def calculate(lessons: list[Lesson], records: list[AttendanceRecord],
                  threshold_percent: int, now: datetime) -> AttendanceStats:
        """Статистика одного студента по одному курсу.

        lessons - все занятия курса за период (в т.ч. будущие);
        records - записи студента; записи других курсов пропускаются.
        """
        course_lesson_ids = {lesson.pk for lesson in lessons}

        present = 0
        missed = 0
        marked_lesson_ids = set()
        for record in records:
            if record.lesson_id not in course_lesson_ids:
                continue
            if record.status == AttendanceStatus.PRESENT:
                present += 1
            elif record.status == AttendanceStatus.ABSENT:
                missed += 1
            else:
                continue  # NOT_MARKED не считается
            marked_lesson_ids.add(record.lesson_id)

        not_marked = 0
        for lesson in lessons:
            if lesson.has_started(now) and lesson.pk not in marked_lesson_ids:
                not_marked += 1

        marked = present + missed
        allowed = AttendanceCalculator.allowed_misses(len(lessons), missed, threshold_percent)

        return AttendanceStats(
            total=len(lessons),
            marked=marked,
            present=present,
            missed=missed,
            not_marked=not_marked,
            percent=AttendanceCalculator.current_percent(marked, missed),
            allowed_misses=allowed,
            level=AttendanceCalculator.get_level(allowed),
        )
