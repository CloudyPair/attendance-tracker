"""Разовый импорт расписания из .ics (sequence_schedule_import.puml).

Вызывать будет management-команда `manage.py import_schedule <группа> <файл.ics>`.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
from itertools import islice
from io import BytesIO
import json
import os
import re
import tempfile
from typing import BinaryIO

from dateutil.rrule import rruleset, rrulestr
from django.db import IntegrityError, transaction
from django.conf import settings
from django.utils import timezone
from icalendar import Calendar

from attendance.errors import InvalidChangeError
from attendance.models import Course, Group, Lesson, LessonType, Subject, Teacher


@dataclass(frozen=True, kw_only=True)
class ImportResult:
    created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class ScheduleImporter:
    def import_miet(self, group_id: int, source_name: str = "") -> ImportResult:
        from .miet import MietScheduleClient

        group = Group.objects.get(pk=group_id)
        if Lesson.objects.filter(course__group=group).exists():
            raise InvalidChangeError("У группы уже есть занятия. Повторная загрузка не поддерживается")
        calendar = MietScheduleClient().download(source_name or group.name)
        result = self.import_ics(BytesIO(calendar.content), group.pk, semester=calendar.semester)
        if result.errors:
            raise InvalidChangeError("; ".join(result.errors))
        return result

    def _store_calendar(self, group: Group, content: bytes, semester: str, semester_start: date, source: str = "") -> None:
        directory = settings.MEDIA_ROOT / "schedules"
        metadata = {"group": group.name, "semester": semester,
                    "semester_start": semester_start.strftime("%d-%m-%Y"), "source": source}
        try:
            directory.mkdir(parents=True, exist_ok=True)
            for suffix, value in (("ics", content), ("json", json.dumps(metadata, ensure_ascii=False).encode("utf-8"))):
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
                    temporary.write(value)
                    temporary_path = temporary.name
                os.replace(temporary_path, directory / f"{group.pk}.{suffix}")
        except OSError as error:
            raise InvalidChangeError("Не удалось сохранить файл расписания на сервере") from error

    def import_ics(self, file: BinaryIO, group_id: int, *, semester: str) -> ImportResult:
        """1. У группы уже есть занятия -> отказ (импорт разовый).
        2. Разобрать календарь (библиотека icalendar), развернуть повторения.
        3. В одной транзакции: пропустить служебные события; создать Subject и
           Course, найти существующего Teacher; сохранить Lesson и исходный файл.
        4. Любая ошибка разбора -> откат, ImportResult с ошибками.
        """
        try:
            if not semester.strip() or len(semester) > 20:
                raise InvalidChangeError("Укажите семестр длиной до 20 символов")
            content = file.read(10 * 1024 * 1024 + 1)
            if len(content) > 10 * 1024 * 1024:
                raise InvalidChangeError("Календарь больше 10 МБ")
            calendar = Calendar.from_ical(content)
            created = skipped = 0
            with transaction.atomic():
                group = Group.objects.select_for_update().get(pk=group_id)
                if Lesson.objects.filter(course__group=group).exists():
                    raise InvalidChangeError("У группы уже есть занятия. Повторный импорт не поддерживается")
                for event in calendar.walk("VEVENT"):
                    if self._is_service_event(event):
                        skipped += 1
                        continue
                    data = self._parse_occurrence(event)
                    subject, _ = Subject.objects.get_or_create(name=data["subject"])
                    course, _ = Course.objects.get_or_create(group=group, subject=subject, semester=semester.strip())
                    teacher = next((teacher for teacher in Teacher.objects.select_related("user")
                                    if data["teacher_name"] in {
                                        teacher.user.full_name,
                                        f"{teacher.user.last_name} {teacher.user.first_name}".strip()}), None)
                    if teacher:
                        course.teachers.add(teacher)
                    for start in self._expand_recurrence(event):
                        end = start + (data["end_at"] - data["start_at"])
                        uid = sha256(f"{group.pk}:{data['uid']}:{start.isoformat()}".encode()).hexdigest()
                        Lesson.objects.create(course=course, external_uid=uid,
                                              start_at=self._aware(start), end_at=self._aware(end),
                                              type=data["type"], room=data["room"],
                                              teacher_name=data["teacher_name"], teacher=teacher)
                        created += 1
                        if created > 5000:
                            raise InvalidChangeError("Слишком много занятий в календаре")
                if not created:
                    raise InvalidChangeError("В календаре нет учебных занятий")
                first_day = timezone.localtime(Lesson.objects.filter(course__group=group)
                                                .earliest("start_at").start_at).date()
                calendar_start = calendar.get("X-SEMESTER-START")
                semester_start = date.fromisoformat(str(calendar_start)) if calendar_start else first_day
                self._store_calendar(group, content, semester, semester_start, str(calendar.get("X-SOURCE", "")))
            return ImportResult(created=created, skipped=skipped)
        except (ValueError, TypeError, KeyError, IntegrityError, InvalidChangeError) as error:
            return ImportResult(errors=[str(error)])

    def _expand_recurrence(self, vevent) -> list:
        start = vevent.decoded("DTSTART")
        recurrence = rruleset()
        recurrence.rdate(start)
        rules = vevent.get("RRULE")
        if rules:
            if not rules.get("COUNT") and not rules.get("UNTIL"):
                raise InvalidChangeError("Повторение должно содержать COUNT или UNTIL")
            recurrence.rrule(rrulestr(rules.to_ical().decode("ascii"), dtstart=start))
        for key, add in (("RDATE", recurrence.rdate), ("EXDATE", recurrence.exdate)):
            values = vevent.get(key, [])
            if not isinstance(values, list):
                values = [values]
            for value in values:
                for item in value.dts:
                    add(item.dt)
        dates = list(islice(recurrence, 2001))
        if len(dates) > 2000:
            raise InvalidChangeError("Слишком много повторений одного занятия")
        return dates

    def _is_service_event(self, vevent) -> bool:
        return bool(re.fullmatch(r"(?:Числитель|Знаменатель)-(?:I|II)\s*\(\d+\)",
                                 str(vevent.get("SUMMARY", "")).strip(), re.IGNORECASE))

    def _parse_occurrence(self, vevent) -> dict:
        summary = str(vevent.get("SUMMARY", "")).strip()
        match = re.fullmatch(r"(.+?)\s*\[(Лек|Лаб|Пр|Сем)\]", summary, re.IGNORECASE)
        if not match:
            raise InvalidChangeError(f"Не определён предмет или тип занятия: «{summary}»")
        start, end = vevent.decoded("DTSTART"), vevent.decoded("DTEND")
        if not isinstance(start, datetime) or not isinstance(end, datetime) or end <= start:
            raise InvalidChangeError(f"Некорректное время занятия «{summary}»")
        uid = str(vevent.get("UID", "")).strip()
        room = str(vevent.get("LOCATION", ""))
        teacher_name = str(vevent.get("X-TEACHER", "")).strip()
        if not uid or len(match[1].strip()) > 255 or len(room) > 50 or len(teacher_name) > 255:
            raise InvalidChangeError(f"Некорректные реквизиты занятия «{summary}»")
        kind = {"лек": LessonType.LECTURE, "лаб": LessonType.LAB,
                "пр": LessonType.SEMINAR, "сем": LessonType.SEMINAR}[match[2].lower()]
        return {"subject": match[1].strip(), "type": kind, "start_at": start, "end_at": end,
                "uid": uid, "room": room, "teacher_name": teacher_name}

    @staticmethod
    def _aware(moment: datetime) -> datetime:
        return moment if timezone.is_aware(moment) else timezone.make_aware(moment, timezone.get_default_timezone())
