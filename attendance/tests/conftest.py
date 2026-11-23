from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from freezegun import freeze_time
import pytest

from attendance.models import Course, Group, GroupRole, Lesson, LessonType, Student, Subject, Teacher, User
from attendance.services import build_services


@pytest.fixture(autouse=True)
def test_environment(settings, tmp_path):
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.TELEGRAM_BOT_USERNAME = ""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = tmp_path / "media"
    with freeze_time("2026-11-23 09:00:00+00:00"):
        yield


class FakeClock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


@pytest.fixture
def sample(db):
    group = Group.objects.create(name="ИВТ-ТЕСТ")
    other_group = Group.objects.create(name="Другая группа")

    def student(username, role, group=group):
        user = User.objects.create_user(username=username, password="test-password", last_name=username)
        return Student.objects.create(user=user, group=group, role=role)

    headman = student("headman", GroupRole.HEADMAN)
    deputy = student("deputy", GroupRole.DEPUTY)
    member = student("member", GroupRole.MEMBER)
    outsider = student("outsider", GroupRole.HEADMAN, other_group)
    teacher = Teacher.objects.create(user=User.objects.create_user("teacher", password="test-password"))
    foreign_teacher = Teacher.objects.create(user=User.objects.create_user("foreign_teacher"))
    course = Course.objects.create(group=group, subject=Subject.objects.create(name="Технологии программирования"),
                                   semester="Осень 2026")
    course.teachers.add(teacher)
    now = datetime(2026, 11, 23, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    lesson = Lesson.objects.create(course=course, start_at=now.replace(hour=9),
                                    end_at=now.replace(hour=10, minute=20), type=LessonType.LECTURE)
    clock = FakeClock(now)
    return SimpleNamespace(group=group, other_group=other_group, headman=headman, deputy=deputy,
                           member=member, outsider=outsider, teacher=teacher, foreign_teacher=foreign_teacher,
                           course=course, lesson=lesson, now=now, clock=clock, services=build_services(clock=clock))
