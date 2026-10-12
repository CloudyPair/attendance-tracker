"""Отчёт преподавателя по курсу (value objects)."""
from dataclasses import dataclass, field
from datetime import datetime

from attendance.models import Course, Lesson, LessonType, Student

from .calculator import AttendanceStats


@dataclass(frozen=True, kw_only=True)
class ReportRow:
    student: Student
    by_type: dict[LessonType, AttendanceStats] = field(default_factory=dict)
    total: AttendanceStats
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class CourseReport:
    course: Course
    from_: datetime
    to: datetime
    rows: list[ReportRow] = field(default_factory=list)
    unmarked_lessons: list[Lesson] = field(default_factory=list)
