"""Отметка и чтение расписания. Версия ведомости защищает от устаревших форм."""
from datetime import datetime
from functools import partial

from django.db import OperationalError, transaction
from django.db.models import Count, F, Prefetch, Q

from attendance.errors import AccessDeniedError, ConcurrentChangeError, InvalidChangeError
from attendance.models import (AttendanceRecord, AttendanceStatus, ChangeSource, DisputeStatus,
                               Lesson, NotificationType, Student, Teacher)

from .interfaces import IClock
from .notifications import NotificationService
from .policy import AccessPolicy
from .statistics import StatisticsService
from .calculator import WarningLevel
from .reports import LessonSummary


class AttendanceService:
    def __init__(self, clock: IClock, policy: AccessPolicy,
                 statistics: StatisticsService, notifications: NotificationService):
        self.clock = clock
        self.policy = policy
        self.statistics = statistics
        self.notifications = notifications

    def open_lesson(self, user: Student, lesson_id: int) -> list[AttendanceRecord]:
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().select_related("course__group").get(pk=lesson_id)
            if not self.policy.can_mark(user, lesson, self.clock.now()):
                raise AccessDeniedError("Отметка доступна ответственному за группу только в день занятия")
            students = list(Student.objects.filter(group_id=lesson.course.group_id))
            AttendanceRecord.objects.bulk_create(
                [AttendanceRecord(lesson=lesson, student=student) for student in students],
                ignore_conflicts=True)
            return list(lesson.records.filter(student__group_id=lesson.course.group_id)
                        .select_related("student__user", "student__group")
                        .order_by("student__user__last_name", "student__user__first_name", "pk"))

    def save_marks(self, user: Student, lesson_id: int,
                   marks: dict[int, AttendanceStatus], reason: str = "", *, expected_version: int,
                   reasons: dict[int, str] | None = None) -> None:
        """marks: student_id -> PRESENT/ABSENT; неизменённые записи пропускаются.

        1. can_mark для занятия; can_edit для уже отмеченных записей.
        2. Запомнить уровни предупреждения затронутых студентов (statistics).
        3. transaction.atomic + select_for_update записей:
           record.change(...) -> UPDATE AttendanceRecord + INSERT AttendanceChange.
           Ошибка/IntegrityError -> откат, «Данные изменились, обновите страницу».
        4. После commit: пересчитать уровни; если ухудшился -
           notifications.notify(student, THRESHOLD_WARNING, ...).
        """
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise InvalidChangeError("Некорректная версия ведомости")
        try:
            with transaction.atomic():
                lesson = Lesson.objects.select_for_update().select_related(
                    "course__group", "course__subject").get(pk=lesson_id)
                now = self.clock.now()
                if not self.policy.can_mark(user, lesson, now):
                    raise AccessDeniedError("Нет права отмечать это занятие или окно отметки уже закрыто")
                if lesson.marking_version != expected_version:
                    raise ConcurrentChangeError("Данные изменились. Обновите страницу и повторите правку")
                students = {student.pk: student for student in Student.objects.filter(
                    group_id=lesson.course.group_id).select_related("user")}
                if any(isinstance(pk, bool) or pk not in students for pk in marks):
                    raise AccessDeniedError("В ведомости есть студент другой группы")
                if any(status not in AttendanceStatus.values for status in marks.values()):
                    raise InvalidChangeError("Неизвестный статус посещаемости")
                records = {record.student_id: record for record in lesson.records.select_for_update()}
                changed = [(pk, status) for pk, status in marks.items()
                           if status != (records[pk].status if pk in records else AttendanceStatus.NOT_MARKED)]
                if not changed:
                    return
                before = {pk: self.statistics.for_student_course(students[pk], lesson.course).level
                          for pk, _ in changed}
                # CAS защищает запись и на SQLite, где SELECT FOR UPDATE не действует.
                if Lesson.objects.filter(pk=lesson_id, marking_version=expected_version).update(
                        marking_version=F("marking_version") + 1) != 1:
                    raise ConcurrentChangeError("Данные изменились. Обновите страницу")
                for pk, status in changed:
                    record = records.get(pk) or AttendanceRecord.objects.create(
                        lesson=lesson, student=students[pk])
                    record.change(status, user, (reasons or {}).get(pk, reason), now)
                self._notify_worsened(lesson, students, before)
        except OperationalError as error:
            if "locked" in str(error).lower():
                raise ConcurrentChangeError("Ведомость сохраняется другим пользователем. Обновите страницу") from error
            raise

    def correct_record(self, actor: Student | Teacher, record_id: int, new_status: AttendanceStatus,
                       reason: str, source: ChangeSource) -> None:
        """Одиночная правка (в т.ч. из спора, source = DISPUTE - без проверки окна правки)."""
        with transaction.atomic():
            # Единый порядок блокировок: занятие, затем его записи.
            lesson_id = AttendanceRecord.objects.values_list("lesson_id", flat=True).get(pk=record_id)
            lesson = Lesson.objects.select_for_update().select_related("course__subject").get(pk=lesson_id)
            record = AttendanceRecord.objects.select_for_update().select_related(
                "student", "lesson__course__group").get(pk=record_id)
            if source == ChangeSource.DISPUTE:
                dispute = record.disputes.filter(status=DisputeStatus.OPEN).first()
                allowed = dispute is not None and self.policy.can_resolve_dispute(actor, dispute)
            else:
                allowed = source == ChangeSource.EDIT and self.policy.can_edit(actor, record, self.clock.now())
            if not allowed:
                raise AccessDeniedError("Нет права исправлять эту отметку")
            before = {record.student_id: self.statistics.for_student_course(record.student, lesson.course).level}
            record.change(new_status, actor, reason, self.clock.now(), source)
            Lesson.objects.filter(pk=lesson_id).update(marking_version=F("marking_version") + 1)
            self._notify_worsened(lesson, {record.student_id: record.student}, before)

    def get_unmarked_lessons(self, user: Student) -> list[Lesson]:
        """Начавшиеся занятия группы, у которых есть записи NOT_MARKED (или нет записей)."""
        count = Student.objects.filter(group_id=user.group_id).count()
        return list(Lesson.objects.filter(course__group_id=user.group_id, start_at__lte=self.clock.now())
                    .annotate(marked=Count("records", filter=Q(records__status__in=[
                        AttendanceStatus.PRESENT, AttendanceStatus.ABSENT],
                        records__student__group_id=user.group_id)))
                    .filter(marked__lt=count).select_related("course__subject").order_by("start_at"))

    def lessons_for_student(self, user: Student, from_: datetime, to: datetime) -> list[LessonSummary]:
        self.statistics._check_period(from_, to)
        lessons = Lesson.objects.filter(course__group_id=user.group_id, start_at__gte=from_, start_at__lt=to)
        lessons = lessons.select_related("course__subject", "teacher__user").annotate(
            marked=Count("records", filter=Q(records__status__in=[AttendanceStatus.PRESENT, AttendanceStatus.ABSENT],
                                              records__student__group_id=user.group_id)))
        lessons = lessons.prefetch_related(Prefetch("records", queryset=AttendanceRecord.objects.filter(
            student=user), to_attr="own_records"))
        now = self.clock.now()
        responsible = user.is_headman_or_deputy() or user.has_active_delegation(now)
        total = Student.objects.filter(group_id=user.group_id).count()
        return [LessonSummary(lesson=lesson,
                              status=lesson.own_records[0].status if lesson.own_records else AttendanceStatus.NOT_MARKED,
                              marked_students=lesson.marked, total_students=total,
                              can_mark=responsible and lesson.is_marking_window_open(now))
                for lesson in lessons.order_by("start_at", "pk")]

    def is_responsible(self, user: Student) -> bool:
        return user.is_headman_or_deputy() or user.has_active_delegation(self.clock.now())

    def lesson_for_marking(self, user: Student, lesson_id: int) -> Lesson:
        lesson = Lesson.objects.select_related("course__subject", "course__group", "teacher__user").get(pk=lesson_id)
        if not self.policy.can_mark(user, lesson, self.clock.now()):
            raise AccessDeniedError("Вы не можете отмечать это занятие")
        return lesson

    def _notify_worsened(self, lesson, students, before) -> None:
        order = {WarningLevel.OK: 0, WarningLevel.WARNING: 1, WarningLevel.BELOW_THRESHOLD: 2}
        for pk, old_level in before.items():
            stats = self.statistics.for_student_course(students[pk], lesson.course)
            if order[stats.level] > order[old_level]:
                text = (f"{lesson.course.subject.name}: осталось допустимых пропусков — "
                        f"{stats.allowed_misses}. Порог посещаемости {lesson.course.threshold_percent}%.")
                transaction.on_commit(partial(self.notifications.notify, students[pk],
                                               NotificationType.THRESHOLD_WARNING, text), robust=True)
