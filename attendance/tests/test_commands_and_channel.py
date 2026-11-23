from datetime import date
from io import BytesIO, StringIO
import json

from django.core.management import call_command, CommandError
from django.utils import timezone
import pytest

from attendance.models import AttendanceChange, AttendanceRecord, AttendanceStatus as S, Group, Lesson, Student
from attendance.services.telegram_channel import TelegramChannel

pytestmark = pytest.mark.django_db


def test_demo_filling_is_reproducible_and_preserves_manual_marks():
    output = StringIO()
    call_command("seed_demo", stdout=output)
    before = dict(AttendanceRecord.objects.values_list("pk", "status"))
    call_command("fill_demo_attendance", through=date(2026, 11, 23), stdout=output)
    past = Lesson.objects.filter(end_at__lte=timezone.now()).count()
    for student in Student.objects.all():
        records = AttendanceRecord.objects.filter(student=student, lesson__end_at__lte=timezone.now())
        assert records.count() == past
        assert not records.filter(status=S.NOT_MARKED).exists()
        assert .8 <= records.filter(status=S.PRESENT).count() / past <= .9
    assert dict(AttendanceRecord.objects.filter(pk__in=before).values_list("pk", "status")) == before
    total, history = AttendanceRecord.objects.count(), AttendanceChange.objects.count()
    call_command("fill_demo_attendance", through=date(2026, 11, 23), stdout=output)
    assert (AttendanceRecord.objects.count(), AttendanceChange.objects.count()) == (total, history)


def test_fill_without_demo_has_clear_error():
    with pytest.raises(CommandError, match="seed_demo"):
        call_command("fill_demo_attendance")


def test_import_command_reports_success_and_rejects_repeat(tmp_path):
    from attendance.tests.test_import import calendar_file
    group = Group.objects.create(name="Команда импорта")
    source = tmp_path / "schedule.ics"
    source.write_bytes(calendar_file(repeat=False).getvalue())
    output = StringIO()
    call_command("import_schedule", group.name, str(source), semester="Осень 2026", stdout=output)
    assert Lesson.objects.filter(course__group=group).exists()
    with pytest.raises(CommandError):
        call_command("import_schedule", group.name, str(source), semester="Осень 2026", stdout=output)
    with pytest.raises(CommandError):
        call_command("import_schedule", "Нет группы", str(source), semester="Осень 2026", stdout=output)


def test_runbot_requires_config_and_runs_separate_process_entrypoint(settings, monkeypatch):
    with pytest.raises(CommandError, match="TELEGRAM_BOT_TOKEN"):
        call_command("runbot", stdout=StringIO())
    invoked = []
    async def offline_run(on_ready=None):
        invoked.append(True)
        on_ready()
    settings.TELEGRAM_BOT_TOKEN = "offline-test-token"
    monkeypatch.setattr("attendance.management.commands.runbot.run_bot", offline_run)
    output = StringIO()
    call_command("runbot", stdout=output)
    assert invoked == [True]
    assert "Polling запущен" in output.getvalue()


@pytest.mark.parametrize("reply,expected", [(b'{"ok": true}', True), (b'{"ok": false}', False), (b"invalid", False)])
def test_notification_transport_checks_response_and_normalizes_text(settings, monkeypatch, reply, expected):
    settings.TELEGRAM_BOT_TOKEN = "offline-test-token"
    requests = []
    def fake_api(request, **kwargs):
        requests.append(request)
        return BytesIO(reply)
    monkeypatch.setattr("attendance.services.telegram_channel.urlopen", fake_api)
    assert TelegramChannel().send("321", "Учёт · посещаемости") is expected
    body = json.loads(requests[0].data)
    assert body == {"chat_id": "321", "text": "Учет  посещаемости"}


def test_notification_timeout_is_not_raised_or_logged_with_secret(settings, monkeypatch, caplog):
    settings.TELEGRAM_BOT_TOKEN = "offline-test-token"
    def timeout(*args, **kwargs):
        raise TimeoutError("offline-test-token")
    monkeypatch.setattr("attendance.services.telegram_channel.urlopen", timeout)
    assert TelegramChannel().send("321", "Порог") is False
    assert "offline-test-token" not in caplog.text
    settings.TELEGRAM_BOT_TOKEN = ""
    assert TelegramChannel().send("321", "Порог") is False
