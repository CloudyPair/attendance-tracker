"""Заполнить только пустые отметки учебной ИВТ-31, сохраняя ручные изменения."""
from datetime import date, datetime, time
from math import ceil, floor
import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from attendance.models import (AttendanceChange, AttendanceRecord, AttendanceStatus, ChangeSource,
                               GroupRole, Lesson, Student)
from attendance.timeutils import next_midnight


class Command(BaseCommand):
    help = "Заполнить прошедшие занятия ИВТ-31: у каждого студента 80–90% посещаемости"

    def add_arguments(self, parser):
        parser.add_argument("--through", type=date.fromisoformat, default=date(2026, 11, 23))
        parser.add_argument("--seed", type=int, default=23)

    @transaction.atomic
    def handle(self, *args, **options):
        students = list(Student.objects.filter(group__name="ИВТ-31",
            user__username__in=[f"ivt31_{index:02d}" for index in range(1, 16)]).select_related("user"))
        if len(students) != 15:
            raise CommandError("Сначала создайте 15 учебных студентов командой seed_demo")
        marker = next((student for student in students if student.role == GroupRole.HEADMAN), None)
        if marker is None:
            raise CommandError("В учебной группе не назначен староста")
        now = timezone.now()
        cutoff = next_midnight(timezone.make_aware(datetime.combine(options["through"], time.min)))
        lessons = list(Lesson.objects.filter(course__group_id=marker.group_id,
                       start_at__lt=cutoff, end_at__lte=now).order_by("start_at", "pk"))
        if not lessons:
            raise CommandError("Нет прошедших занятий до указанной даты")
        existing = {(record.student_id, record.lesson_id): record for record in
                    AttendanceRecord.objects.filter(student__in=students, lesson__in=lessons)}
        generator = random.Random(options["seed"])
        new, updated, changed_lessons, pending_history = [], [], set(), []
        for student in students:
            marked = {lesson.pk: existing[(student.pk, lesson.pk)] for lesson in lessons
                      if (student.pk, lesson.pk) in existing
                      and existing[(student.pk, lesson.pk)].status != AttendanceStatus.NOT_MARKED}
            present = sum(record.status == AttendanceStatus.PRESENT for record in marked.values())
            empty = [lesson for lesson in lessons if lesson.pk not in marked]
            minimum, maximum = max(ceil(len(lessons) * .8), present), min(floor(len(lessons) * .9), present + len(empty))
            if minimum > maximum:
                raise CommandError(f"Сохраненные отметки {student.user.username} не позволяют получить 80–90% без перезаписи")
            target = generator.randint(minimum, maximum)
            attending = {lesson.pk for lesson in generator.sample(empty, target - present)}
            for lesson in empty:
                record = existing.get((student.pk, lesson.pk))
                is_new = record is None
                if is_new:
                    record = AttendanceRecord(lesson=lesson, student=student)
                record.status = AttendanceStatus.PRESENT if lesson.pk in attending else AttendanceStatus.ABSENT
                record.marked_by = marker
                record.marked_at = record.last_changed_at = lesson.end_at
                (new if is_new else updated).append(record)
                pending_history.append(record)
                changed_lessons.add(lesson.pk)
            self.stdout.write(f"{student.user.username}: {target * 100 // len(lessons)}% ({target}/{len(lessons)})")
        AttendanceRecord.objects.bulk_create(new)
        AttendanceRecord.objects.bulk_update(updated, ["status", "marked_by", "marked_at", "last_changed_at"])
        AttendanceChange.objects.bulk_create([
            AttendanceChange(record=record, old_status=AttendanceStatus.NOT_MARKED, new_status=record.status,
                             changed_by=marker.user, changed_at=record.marked_at, reason="", source=ChangeSource.MARKING)
            for record in pending_history])
        Lesson.objects.filter(pk__in=changed_lessons).update(marking_version=F("marking_version") + 1)
        self.stdout.write(self.style.SUCCESS(f"Занятий: {len(lessons)}; добавлено отметок: {len(pending_history)}. Причины не создавались."))
