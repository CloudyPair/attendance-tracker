from copy import deepcopy
from io import BytesIO
from urllib.error import URLError

from icalendar import Calendar
import pytest

from attendance.errors import InvalidChangeError
from attendance.models import Group, Lesson
from attendance.services.miet import MietScheduleClient
from attendance.services.schedule_import import ScheduleImporter


def payload():
    return {"Semestr": "Осенний семестр 2026/2027", "Data": [{
        "Group": {"Name": "ИВТ-31"}, "DayNumber": 0, "Day": 2,
        "Time": {"Code": 1, "TimeFrom": "2026-09-01T09:00:00", "TimeTo": "2026-09-01T10:20:00"},
        "Class": {"Name": "Операционные системы [Лек]", "TeacherFull": "Преподаватель Сергей Андреевич"},
        "Room": {"Name": "1201 м"}}]}


@pytest.mark.django_db
def test_api_calendar_preserves_teacher_merges_double_class_and_imports_occurrences():
    source = payload()
    second = deepcopy(source["Data"][0])
    second["Time"] = {"Code": 2, "TimeFrom": "2026-09-01T10:30:00", "TimeTo": "2026-09-01T11:50:00"}
    source["Data"].append(second)
    result = MietScheduleClient().build_calendar(source, "ИВТ-31")
    events = Calendar.from_ical(result.content).walk("VEVENT")
    assert len(events) == 1
    assert events[0].decoded("dtend").hour == 11
    assert events[0].decoded("dtend").minute == 50
    assert str(events[0]["X-TEACHER"]) == "Преподаватель Сергей Андреевич"
    group = Group.objects.create(name="ИВТ-31")
    imported = ScheduleImporter().import_ics(BytesIO(result.content), group.pk, semester=result.semester)
    assert not imported.errors
    assert Lesson.objects.count() == 5
    assert not Lesson.objects.exclude(teacher_name="Преподаватель Сергей Андреевич").exists()
    source["Data"].reverse()
    reordered = MietScheduleClient().build_calendar(source, "ИВТ-31")
    assert reordered.content == result.content


@pytest.mark.parametrize("field,value", [("Day", 0), ("Day", 8), ("DayNumber", 4)])
def test_invalid_api_days_are_rejected(field, value):
    source = payload()
    source["Data"][0][field] = value
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().build_calendar(source, "ИВТ-31")


def test_different_group_or_reverse_time_is_rejected():
    source = payload()
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().build_calendar(source, "Другая группа")
    source["Data"][0]["Time"]["TimeTo"] = "2026-09-01T08:00:00"
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().build_calendar(source, "ИВТ-31")


@pytest.mark.parametrize("source", [{"Data": []}, {"Data": [1], "Semestr": "неизвестный год"},
    {"Data": [1], "Semestr": "Лето 2026/2027"}, {"Data": {"invalid": True}}])
def test_missing_or_invalid_term_and_data_are_rejected(source):
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().build_calendar(source, "ИВТ-31")


@pytest.mark.parametrize("group", ["", " ", "x" * 51])
def test_invalid_group_does_not_call_network(group, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid input must not access the network")
    monkeypatch.setattr("attendance.services.miet.urlopen", unexpected)
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().download(group)


@pytest.mark.parametrize("raw", [b"not-json", b"null", b'{"Data": [1]}', b"x" * (5 * 1024 * 1024 + 1)],
                         ids=["invalid-json", "null-payload", "missing-term", "oversized-response"])
def test_bad_api_responses_have_domain_errors(raw, monkeypatch):
    monkeypatch.setattr("attendance.services.miet.urlopen", lambda *a, **kw: BytesIO(raw))
    with pytest.raises(InvalidChangeError):
        MietScheduleClient().download("ИВТ-31")


def test_network_failure_is_an_actionable_domain_error(monkeypatch):
    def offline(*args, **kwargs):
        raise URLError("offline")
    monkeypatch.setattr("attendance.services.miet.urlopen", offline)
    with pytest.raises(InvalidChangeError, match="недоступен"):
        MietScheduleClient().download("ИВТ-31")
