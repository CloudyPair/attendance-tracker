from datetime import timedelta

import pytest

from attendance.errors import (AccessDeniedError, ConcurrentChangeError, InvalidChangeError,
                                ReasonRequiredError)
from attendance.models import (AttendanceChange, AttendanceRecord, AttendanceStatus as S,
                               ChangeSource, Delegation, Dispute, Lesson, Notification, TelegramLink)
from attendance.services import build_services


pytestmark = pytest.mark.django_db


def test_open_creates_one_record_per_student_and_is_idempotent(sample):
    service = sample.services.attendance
    assert len(service.open_lesson(sample.headman, sample.lesson.pk)) == 3
    service.open_lesson(sample.deputy, sample.lesson.pk)
    assert AttendanceRecord.objects.count() == 3
    assert set(AttendanceRecord.objects.values_list("status", flat=True)) == {S.NOT_MARKED}


@pytest.mark.parametrize("actor", ["member", "outsider"])
def test_open_requires_role_and_own_group(sample, actor):
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.open_lesson(getattr(sample, actor), sample.lesson.pk)
    assert not AttendanceRecord.objects.exists()


def test_first_mark_records_actor_source_and_time(sample):
    sample.services.attendance.save_marks(sample.headman, sample.lesson.pk,
        {sample.member.pk: S.ABSENT}, expected_version=0)
    record = AttendanceRecord.objects.get(student=sample.member)
    assert record.status == S.ABSENT
    assert record.marked_at == sample.now
    assert record.marked_by == sample.headman
    assert record.changes.get().source == ChangeSource.MARKING
    sample.lesson.refresh_from_db()
    assert sample.lesson.marking_version == 1


def test_edit_without_reason_rolls_back_entire_batch(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    with pytest.raises(ReasonRequiredError):
        sample.services.attendance.save_marks(sample.headman, sample.lesson.pk,
            {sample.deputy.pk: S.PRESENT, sample.member.pk: S.PRESENT}, expected_version=0)
    assert AttendanceRecord.objects.count() == 1
    assert AttendanceChange.objects.count() == 1
    assert AttendanceRecord.objects.get(pk=record.pk).status == S.ABSENT
    assert Lesson.objects.get(pk=sample.lesson.pk).marking_version == 0
    assert not Notification.objects.exists()


def test_edit_with_reason_keeps_first_marker_and_creates_audit_entry(sample):
    service = sample.services.attendance
    service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.ABSENT}, expected_version=0)
    service.save_marks(sample.deputy, sample.lesson.pk, {sample.member.pk: S.PRESENT},
                       "Студент пришёл", expected_version=1)
    record = AttendanceRecord.objects.get(student=sample.member)
    assert record.marked_by == sample.headman
    entry = record.changes.latest("pk")
    assert (entry.old_status, entry.new_status, entry.source) == (S.ABSENT, S.PRESENT, ChangeSource.EDIT)
    assert entry.changed_by == sample.deputy.user


def test_stale_form_does_not_overwrite_newer_marks(sample):
    service = sample.services.attendance
    service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.ABSENT}, expected_version=0)
    with pytest.raises(ConcurrentChangeError):
        service.save_marks(sample.deputy, sample.lesson.pk, {sample.member.pk: S.PRESENT},
                           "Старая форма", expected_version=0)
    assert AttendanceRecord.objects.get(student=sample.member).status == S.ABSENT
    assert AttendanceChange.objects.count() == 1


@pytest.mark.parametrize("status", ["UNKNOWN", "", None])
def test_unknown_status_is_rejected(sample, status):
    with pytest.raises(InvalidChangeError):
        sample.services.attendance.save_marks(sample.headman, sample.lesson.pk,
            {sample.member.pk: status}, expected_version=0)
    assert not AttendanceRecord.objects.exists()


def test_cannot_mark_another_group_student(sample):
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.save_marks(sample.headman, sample.lesson.pk,
            {sample.outsider.pk: S.PRESENT}, expected_version=0)


def test_unchanged_marks_do_not_add_history_or_increment_version(sample):
    service = sample.services.attendance
    service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.PRESENT}, expected_version=0)
    service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.PRESENT}, expected_version=1)
    assert AttendanceChange.objects.count() == 1
    assert Lesson.objects.get(pk=sample.lesson.pk).marking_version == 1


def test_cannot_clear_saved_mark(sample):
    service = sample.services.attendance
    service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.PRESENT}, expected_version=0)
    with pytest.raises(InvalidChangeError):
        service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.NOT_MARKED},
                           "Очистить", expected_version=1)


@pytest.mark.parametrize(("hour", "minute", "day", "allowed"), [(0, 0, 23, True), (23, 59, 23, True), (0, 0, 24, False)])
def test_marking_day_boundaries(sample, hour, minute, day, allowed):
    sample.clock.moment = sample.now.replace(day=day, hour=hour, minute=minute)
    if allowed:
        sample.services.attendance.open_lesson(sample.headman, sample.lesson.pk)
    else:
        with pytest.raises(AccessDeniedError):
            sample.services.attendance.open_lesson(sample.headman, sample.lesson.pk)


def test_active_delegate_can_mark_but_expired_delegate_cannot(sample):
    Delegation.objects.create(granted_by=sample.headman, delegate=sample.member,
                               granted_at=sample.now - timedelta(hours=1), valid_until=sample.now + timedelta(hours=1))
    sample.services.attendance.open_lesson(sample.member, sample.lesson.pk)
    sample.clock.moment += timedelta(hours=1)
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.open_lesson(sample.member, sample.lesson.pk)


def test_dispute_fix_after_midnight_needs_open_dispute_and_authorized_resolver(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    sample.clock.moment += timedelta(days=1)
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.correct_record(sample.headman, record.pk, S.PRESENT, "Спор", ChangeSource.DISPUTE)
    Dispute.objects.create(record=record, comment="Я был")
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.correct_record(sample.member, record.pk, S.PRESENT, "Спор", ChangeSource.DISPUTE)
    with pytest.raises(AccessDeniedError):
        sample.services.attendance.correct_record(sample.headman, record.pk, S.PRESENT, "Спор №1", ChangeSource.DISPUTE)
    sample.services.attendance.correct_record(sample.teacher, record.pk, S.PRESENT, "Спор №1", ChangeSource.DISPUTE)
    assert AttendanceRecord.objects.get(pk=record.pk).status == S.PRESENT
    assert record.changes.latest("pk").source == ChangeSource.DISPUTE


def test_failed_notification_does_not_undo_marks(sample, django_capture_on_commit_callbacks):
    class FailingChannel:
        def send(self, chat_id, text):
            raise OSError("Telegram недоступен")

    TelegramLink.objects.create(student=sample.member, chat_id="123")
    service = build_services(clock=sample.clock, channel=FailingChannel()).attendance
    with django_capture_on_commit_callbacks(execute=True):
        service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.ABSENT}, expected_version=0)
        assert not Notification.objects.exists()
    assert AttendanceRecord.objects.get(student=sample.member).status == S.ABSENT
    assert Notification.objects.get().sent_at is None


def test_warning_is_sent_after_commit_once(sample, django_capture_on_commit_callbacks):
    class Channel:
        def __init__(self):
            self.messages = []

        def send(self, chat_id, text):
            self.messages.append((chat_id, text))
            return True

    channel = Channel()
    TelegramLink.objects.create(student=sample.member, chat_id="321")
    service = build_services(clock=sample.clock, channel=channel).attendance
    with django_capture_on_commit_callbacks(execute=True):
        service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.ABSENT}, expected_version=0)
        assert channel.messages == []
    assert len(channel.messages) == 1
    assert Notification.objects.get().sent_at == sample.now
    with django_capture_on_commit_callbacks(execute=True):
        service.save_marks(sample.headman, sample.lesson.pk, {sample.member.pk: S.ABSENT}, expected_version=1)
    assert len(channel.messages) == 1
