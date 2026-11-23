from datetime import timedelta

import pytest
from django.db import transaction

from attendance.models import Notification, NotificationType as N, TelegramLink
from attendance.services import build_services

pytestmark = pytest.mark.django_db


class RecordingChannel:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def send(self, chat_id, text):
        self.calls.append((chat_id, text))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_notice_is_delivered_after_commit_and_not_duplicated(sample, django_capture_on_commit_callbacks):
    TelegramLink.objects.create(student=sample.member, chat_id="321", linked_at=sample.now)
    channel = RecordingChannel()
    service = build_services(clock=sample.clock, channel=channel).notifications
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            service.notify(sample.member, N.THRESHOLD_WARNING, "Порог")
            assert channel.calls == []
    item = Notification.objects.get()
    assert item.sent_at == sample.now
    assert channel.calls == [("321", "Порог")]
    service.retry_pending()
    assert len(channel.calls) == 1


@pytest.mark.parametrize("failure", [False, OSError("offline")])
def test_delivery_retries_with_delay_and_stops_after_five_attempts(sample, django_capture_on_commit_callbacks, failure):
    TelegramLink.objects.create(student=sample.member, chat_id="321", linked_at=sample.now)
    channel = RecordingChannel(failure)
    service = build_services(clock=sample.clock, channel=channel).notifications
    with django_capture_on_commit_callbacks(execute=True):
        service.notify(sample.member, N.THRESHOLD_WARNING, "Порог")
    for _ in range(10):
        service.retry_pending()
        sample.clock.moment += timedelta(minutes=1)
    item = Notification.objects.get()
    assert (item.attempts, len(channel.calls)) == (5, 5)
    assert item.sent_at is None


def test_retry_can_recover_from_failure(sample, django_capture_on_commit_callbacks):
    TelegramLink.objects.create(student=sample.member, chat_id="321", linked_at=sample.now)
    channel = RecordingChannel(False)
    service = build_services(clock=sample.clock, channel=channel).notifications
    with django_capture_on_commit_callbacks(execute=True):
        service.notify(sample.member, N.THRESHOLD_WARNING, "Порог")
    sample.clock.moment += timedelta(seconds=59)
    channel.result = True
    service.retry_pending()
    assert len(channel.calls) == 1
    sample.clock.moment += timedelta(seconds=1)
    service.retry_pending()
    assert Notification.objects.get().sent_at is not None


@pytest.mark.parametrize("linked,enabled", [(False, False), (True, False)])
def test_unlinked_or_muted_student_has_no_future_backlog(sample, linked, enabled):
    if linked:
        TelegramLink.objects.create(student=sample.member, chat_id="321", notifications_enabled=enabled)
    channel = RecordingChannel()
    service = build_services(clock=sample.clock, channel=channel).notifications
    service.notify(sample.member, N.THRESHOLD_WARNING, "Порог")
    assert Notification.objects.get().skipped
    service.retry_pending()
    assert channel.calls == []


def test_old_pending_notice_is_not_sent_to_new_binding(sample):
    notice = Notification.objects.create(recipient=sample.member, type=N.THRESHOLD_WARNING,
        text="Старое", created_at=sample.now - timedelta(days=1))
    TelegramLink.objects.create(student=sample.member, chat_id="321", linked_at=sample.now)
    channel = RecordingChannel()
    build_services(clock=sample.clock, channel=channel).notifications.retry_pending()
    notice.refresh_from_db()
    assert notice.skipped
    assert channel.calls == []


def test_rolled_back_action_does_not_enqueue_or_send_notice(sample):
    TelegramLink.objects.create(student=sample.member, chat_id="321")
    channel = RecordingChannel()
    service = build_services(clock=sample.clock, channel=channel).notifications
    with pytest.raises(ValueError):
        with transaction.atomic():
            service.notify(sample.member, N.THRESHOLD_WARNING, "Откат")
            raise ValueError("cancel transaction")
    assert not Notification.objects.exists()
    assert channel.calls == []
