from datetime import timedelta

import pytest

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import LinkToken, Notification, NotificationType, TelegramLink

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("elapsed,valid", [(timedelta(minutes=15, microseconds=-1), True),
    (timedelta(minutes=15), False), (timedelta(minutes=15, microseconds=1), False)])
def test_one_time_link_expires_at_exact_boundary(sample, elapsed, valid):
    service = sample.services.telegram_link
    token = service.create_link_token(sample.member)
    sample.clock.moment += elapsed
    if valid:
        link = service.bind(token, "321")
        assert link.student == sample.member
        with pytest.raises(InvalidChangeError):
            service.bind(token, "321")
    else:
        with pytest.raises(InvalidChangeError):
            service.bind(token, "321")
        assert not TelegramLink.objects.exists()


@pytest.mark.parametrize("chat", ["-100123", "0", "abc", ""])
def test_binding_accepts_only_personal_chats(sample, chat):
    token = sample.services.telegram_link.create_link_token(sample.member)
    with pytest.raises(InvalidChangeError):
        sample.services.telegram_link.bind(token, chat)
    assert LinkToken.objects.get(token=token).used_at is None


def test_new_link_invalidates_previous_and_cannot_steal_another_account(sample):
    service = sample.services.telegram_link
    old = service.create_link_token(sample.member)
    current = service.create_link_token(sample.member)
    with pytest.raises(InvalidChangeError):
        service.bind(old, "321")
    service.bind(current, "321")
    other = service.create_link_token(sample.headman)
    with pytest.raises(InvalidChangeError):
        service.bind(other, "321")
    assert service.student_for_chat("321") == sample.member
    assert LinkToken.objects.get(token=other).used_at is None
    service.bind(service.create_link_token(sample.member), "654")
    with pytest.raises(AccessDeniedError):
        service.student_for_chat("321")
    assert service.student_for_chat("654") == sample.member


def test_disabled_user_cannot_bind_or_access_bot(sample):
    service = sample.services.telegram_link
    token = service.create_link_token(sample.member)
    sample.member.user.is_active = False
    sample.member.user.save(update_fields=["is_active"])
    with pytest.raises(InvalidChangeError):
        service.bind(token, "321")
    TelegramLink.objects.create(student=sample.member, chat_id="321")
    with pytest.raises(AccessDeniedError):
        service.student_for_chat("321")


def test_logout_invalidates_tokens_pending_messages_and_old_buttons(sample):
    service = sample.services.telegram_link
    service.bind(service.create_link_token(sample.member), "321")
    pending_token = service.create_link_token(sample.member)
    notice = Notification.objects.create(recipient=sample.member, type=NotificationType.THRESHOLD_WARNING, text="Порог")
    service.unlink_chat("321")
    service.unlink_chat("321")
    assert service.get_link(sample.member) is None
    assert LinkToken.objects.get(token=pending_token).used_at is not None
    notice.refresh_from_db()
    assert notice.skipped
    with pytest.raises(AccessDeniedError):
        service.student_for_chat("321")


def test_notification_toggle_discards_pending_but_preserves_link(sample):
    service = sample.services.telegram_link
    with pytest.raises(InvalidChangeError):
        service.set_notifications(sample.member, False)
    service.bind(service.create_link_token(sample.member), "321")
    notice = Notification.objects.create(recipient=sample.member, type=NotificationType.THRESHOLD_WARNING, text="Порог")
    service.set_notifications(sample.member, False)
    notice.refresh_from_db()
    assert notice.skipped
    assert not service.get_link(sample.member).notifications_enabled
    service.set_notifications(sample.member, True)
    assert service.get_link(sample.member).notifications_enabled


def test_unknown_token_has_no_side_effects(sample):
    with pytest.raises(InvalidChangeError):
        sample.services.telegram_link.bind("unknown", "321")
    assert not TelegramLink.objects.exists()
