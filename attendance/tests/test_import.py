from datetime import datetime, timedelta
from io import BytesIO

from django.conf import settings
from django.core.management import call_command
from icalendar import Calendar, Event
import pytest

from attendance.models import AttendanceRecord, Group, Lesson, Student, Subject, Teacher
from attendance.services.schedule_import import ScheduleImporter


pytestmark = pytest.mark.django_db


def calendar_file(*, invalid=False, repeat=True):
    calendar = Calendar()
    event = Event()
    event.add("uid", "one")
    event.add("summary", "Тестовый предмет [Лаб]")
    event.add("dtstart", datetime(2026, 9, 1, 9))
    event.add("dtend", datetime(2026, 9, 1, 11, 50))
    event.add("location", "1234")
    event.add("X-TEACHER", "Преподаватель из API")
    if repeat:
        event.add("rrule", {"freq": "weekly", "interval": 4, "count": 3})
        event.add("exdate", datetime(2026, 9, 29, 9))
    calendar.add_component(event)
    if invalid:
        broken = Event()
        broken.add("summary", "Без типа")
        calendar.add_component(broken)
    return BytesIO(calendar.to_ical())


def test_repeat_expansion_exclusion_timezone_and_teacher_metadata():
    group = Group.objects.create(name="Импорт")
    result = ScheduleImporter().import_ics(calendar_file(), group.pk, semester="Осень 2026")
    assert not result.errors
    assert result.created == 2
    lessons = list(Lesson.objects.order_by("start_at"))
    assert lessons[0].start_at.hour == 6  # 09:00 Москвы хранится как UTC 06:00.
    assert lessons[0].end_at - lessons[0].start_at == timedelta(hours=2, minutes=50)
    assert lessons[0].teacher_name == "Преподаватель из API"
    assert lessons[0].teacher_id is None
    assert lessons[0].external_uid != lessons[1].external_uid


def test_import_error_rolls_back_preceding_valid_events():
    group = Group.objects.create(name="Импорт")
    result = ScheduleImporter().import_ics(calendar_file(invalid=True), group.pk, semester="Осень 2026")
    assert result.errors
    assert result.created == 0
    assert not Lesson.objects.exists()
    assert not Subject.objects.exists()


def test_repeat_import_is_rejected_and_uid_is_group_specific():
    first = Group.objects.create(name="Первая")
    second = Group.objects.create(name="Вторая")
    importer = ScheduleImporter()
    assert importer.import_ics(calendar_file(), first.pk, semester="Осень 2026").created == 2
    assert importer.import_ics(calendar_file(), first.pk, semester="Осень 2026").errors
    assert importer.import_ics(calendar_file(), second.pk, semester="Осень 2026").created == 2
    assert Lesson.objects.count() == 4


def test_real_calendar_and_demo_seed_are_minimal_and_idempotent():
    call_command("seed_demo", verbosity=0)
    assert Student.objects.count() == 15
    assert Teacher.objects.count() == 1
    assert Group.objects.count() == 1
    assert Lesson.objects.count() == 300
    assert AttendanceRecord.objects.count() == 30
    assert Lesson.objects.exclude(teacher_name="").count() == 300
    teacher = Teacher.objects.get()
    assert teacher.courses.exists()
    assert Lesson.objects.filter(teacher=teacher).exists()
    before = list(Lesson.objects.values_list("external_uid", "start_at", "end_at"))
    call_command("seed_demo", verbosity=0)
    assert Student.objects.count() == 15
    assert AttendanceRecord.objects.count() == 30
    assert list(Lesson.objects.values_list("external_uid", "start_at", "end_at")) == before


def test_old_demo_runs_after_seed_and_rolls_back_without_touching_real_group():
    call_command("seed_demo", verbosity=0)
    before = (Group.objects.count(), Student.objects.count(), Teacher.objects.count(),
              Lesson.objects.count(), AttendanceRecord.objects.count())
    call_command("demo", no_wait=True)
    assert (Group.objects.count(), Student.objects.count(), Teacher.objects.count(),
            Lesson.objects.count(), AttendanceRecord.objects.count()) == before


def test_duplicate_event_rolls_back_as_import_error():
    group = Group.objects.create(name="Дубликат")
    calendar = Calendar.from_ical(calendar_file(repeat=False).read())
    calendar.add_component(calendar.walk("VEVENT")[0])
    result = ScheduleImporter().import_ics(BytesIO(calendar.to_ical()), group.pk, semester="Осень 2026")
    assert result.errors
    assert not Lesson.objects.exists()
