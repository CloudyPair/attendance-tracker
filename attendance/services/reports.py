"""Отчёт преподавателя по курсу (value objects)."""
from dataclasses import dataclass, field
from datetime import datetime

from attendance.models import AbsenceReason, AttendanceStatus, Course, Lesson, LessonType, Student

from .calculator import AttendanceStats


@dataclass(frozen=True, kw_only=True)
class ReportRow:
    student: Student
    by_type: dict[LessonType, AttendanceStats] = field(default_factory=dict)
    total: AttendanceStats
    reasons: list[str] = field(default_factory=list)
    attachments: list[AbsenceReason] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class CourseReport:
    course: Course
    from_: datetime
    to: datetime
    rows: list[ReportRow] = field(default_factory=list)
    unmarked_lessons: list[Lesson] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class StudentCourseReport:
    course: Course
    total: AttendanceStats
    by_type: dict[LessonType, AttendanceStats] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class LessonSummary:
    lesson: Lesson
    status: str = AttendanceStatus.NOT_MARKED
    marked_students: int = 0
    total_students: int = 0
    can_mark: bool = False

    @property
    def status_label(self) -> str:
        return AttendanceStatus(self.status).label
