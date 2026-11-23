"""Отчёты из общего ядра; интервалы времени полуоткрытые: [from_, to)."""
from datetime import datetime

from django.db.models import Max, Min
from django.utils import timezone

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import (AttendanceChange, AttendanceRecord, AttendanceStatus, Course,
                               Lesson, LessonType, Student, Teacher)
from attendance.timeutils import day_start, next_midnight

from .calculator import AttendanceCalculator, AttendanceStats, WarningLevel
from .interfaces import IClock
from .policy import AccessPolicy
from .reports import CourseReport, ReportRow, StudentCourseReport


class StatisticsService:
    def __init__(self, clock: IClock, policy: AccessPolicy):
        self.clock = clock
        self.policy = policy

    @staticmethod
    def _check_period(from_: datetime, to: datetime) -> None:
        if not timezone.is_aware(from_) or not timezone.is_aware(to) or from_ >= to:
            raise InvalidChangeError("Укажите корректный период: начало должно быть раньше окончания")

    def period_for_student(self, student: Student) -> tuple[datetime, datetime]:
        bounds = Lesson.objects.filter(course__group_id=student.group_id).aggregate(
            first=Min("start_at"), last=Max("start_at"))
        return (day_start(bounds["first"] or self.clock.now()),
                next_midnight(bounds["last"] or self.clock.now()))

    def for_student(self, student: Student, from_: datetime, to: datetime) -> list[StudentCourseReport]:
        self._check_period(from_, to)
        courses = list(Course.objects.filter(group_id=student.group_id).select_related("subject", "group")
                       .order_by("subject__name"))
        lessons = list(Lesson.objects.filter(course__in=courses, start_at__gte=from_, start_at__lt=to))
        records = list(AttendanceRecord.objects.filter(student=student, lesson__in=lessons))
        now = self.clock.now()
        result = []
        for course in courses:
            own_lessons = [lesson for lesson in lessons if lesson.course_id == course.pk]
            if not own_lessons:
                continue
            result.append(StudentCourseReport(
                course=course,
                total=AttendanceCalculator.calculate(own_lessons, records, course.threshold_percent, now),
                by_type={kind: AttendanceCalculator.calculate(
                    [lesson for lesson in own_lessons if lesson.type == kind], records,
                    course.threshold_percent, now) for kind in LessonType
                    if any(lesson.type == kind for lesson in own_lessons)}))
        return result

    def for_student_course(self, student: Student, course: Course) -> AttendanceStats:
        if course.group_id != student.group_id:
            raise AccessDeniedError("Курс относится к другой группе")
        lessons = list(course.lessons.all())
        records = list(AttendanceRecord.objects.filter(student=student, lesson__course=course))
        return AttendanceCalculator.calculate(lessons, records, course.threshold_percent, self.clock.now())

    def period_for_course(self, teacher: Teacher, course: Course) -> tuple[datetime, datetime]:
        if not self.policy.can_view_course(teacher, course):
            raise AccessDeniedError("Этот предмет не закреплен за вами")
        bounds = course.lessons.aggregate(first=Min("start_at"), last=Max("start_at"))
        return day_start(bounds["first"] or self.clock.now()), next_midnight(bounds["last"] or self.clock.now())

    def get_student_history(self, teacher: Teacher, course: Course, student_id: int,
                            from_: datetime, to: datetime) -> list[AttendanceChange]:
        if not self.policy.can_view_course(teacher, course):
            raise AccessDeniedError("Этот предмет не закреплен за вами")
        self._check_period(from_, to)
        if not Student.objects.filter(pk=student_id, group_id=course.group_id).exists():
            raise AccessDeniedError("Студент относится к другой группе")
        return list(AttendanceChange.objects.filter(record__lesson__course=course, record__student_id=student_id,
                    record__lesson__start_at__gte=from_, record__lesson__start_at__lt=to)
                    .select_related("record__lesson", "record__student__user", "changed_by")
                    .order_by("-changed_at", "-pk"))

    def for_course(self, teacher: Teacher, course: Course, from_: datetime, to: datetime) -> CourseReport:
        if not self.policy.can_view_course(teacher, course):
            raise AccessDeniedError("Этот курс не закреплён за вами")
        self._check_period(from_, to)
        lessons = list(course.lessons.filter(start_at__gte=from_, start_at__lt=to))
        students = list(course.group.students.select_related("user").order_by(
            "user__last_name", "user__first_name", "pk"))
        records = list(AttendanceRecord.objects.filter(lesson__in=lessons)
                       .select_related("absence_reason"))
        now = self.clock.now()
        rows = []
        for student in students:
            own = [record for record in records if record.student_id == student.pk]
            rows.append(ReportRow(
                student=student,
                total=AttendanceCalculator.calculate(lessons, own, course.threshold_percent, now),
                by_type={kind: AttendanceCalculator.calculate(
                    [lesson for lesson in lessons if lesson.type == kind], own,
                    course.threshold_percent, now) for kind in LessonType
                    if any(lesson.type == kind for lesson in lessons)},
                reasons=[record.absence_reason.text for record in own
                         if record.status == AttendanceStatus.ABSENT
                         and hasattr(record, "absence_reason")],
                attachments=[record.absence_reason for record in own
                         if record.status == AttendanceStatus.ABSENT
                         and hasattr(record, "absence_reason") and record.absence_reason.attachment]))
        marked = {}
        for record in records:
            if record.status != AttendanceStatus.NOT_MARKED:
                marked[record.lesson_id] = marked.get(record.lesson_id, 0) + 1
        return CourseReport(course=course, from_=from_, to=to, rows=rows,
                            unmarked_lessons=[lesson for lesson in lessons
                                              if lesson.has_started(now)
                                              and marked.get(lesson.pk, 0) < len(students)])

    def students_below_threshold(self, group_id: int) -> list[Student]:
        result = []
        courses = list(Course.objects.filter(group_id=group_id))
        for student in Student.objects.filter(group_id=group_id).select_related("user"):
            if any(course.lessons.exists() and self.for_student_course(student, course).level
                   in (WarningLevel.WARNING, WarningLevel.BELOW_THRESHOLD) for course in courses):
                result.append(student)
        return result

    def get_record_history(self, teacher: Teacher, record_id: int) -> list[AttendanceChange]:
        record = AttendanceRecord.objects.select_related("lesson__course").get(pk=record_id)
        if not self.policy.can_view_course(teacher, record.lesson.course):
            raise AccessDeniedError("История доступна преподавателям курса")
        return list(record.changes.select_related("changed_by").order_by("changed_at", "pk"))
