"""Статистика посещаемости и история отметок (sequence_statistics_export.puml)."""
from datetime import datetime

from attendance.models import AttendanceChange, Course, Student, Teacher

from .calculator import AttendanceStats
from .interfaces import IClock
from .policy import AccessPolicy
from .reports import CourseReport


class StatisticsService:
    def __init__(self, clock: IClock, policy: AccessPolicy):
        self.clock = clock
        self.policy = policy

    def for_student(self, student: Student, from_: datetime, to: datetime) -> list[AttendanceStats]:
        """По каждому курсу группы: AttendanceCalculator.calculate(занятия курса за период,
        записи студента, порог курса, now)."""
        raise NotImplementedError("ЛР4")

    def for_course(self, teacher: Teacher, course: Course, from_: datetime, to: datetime) -> CourseReport:
        """1. policy.can_view_course, иначе AccessDeniedError.
        2. По каждому студенту: общая статистика + по типам занятий, причины пропусков.
        3. unmarked_lessons - начавшиеся занятия с записями NOT_MARKED.
        """
        raise NotImplementedError("ЛР4")

    def students_below_threshold(self, group_id: int) -> list[Student]:
        """Студенты, у которых хотя бы по одному курсу уровень WARNING или BELOW_THRESHOLD."""
        raise NotImplementedError("ЛР4")

    def get_record_history(self, teacher: Teacher, record_id: int) -> list[AttendanceChange]:
        """can_view_course для курса записи; AttendanceChange по записи в порядке времени."""
        raise NotImplementedError("ЛР4")
