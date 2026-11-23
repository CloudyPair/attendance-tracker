from datetime import timedelta

import pytest

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import Notification, NotificationType
from attendance.timeutils import next_midnight

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("grantor", ["headman", "deputy"])
def test_assignment_grants_marking_until_next_midnight(sample, grantor):
    service = sample.services.delegation
    delegation = service.assign(getattr(sample, grantor), sample.member)
    assert delegation.valid_until == next_midnight(sample.now)
    assert sample.services.attendance.is_responsible(sample.member)
    assert service.active_for(sample.member) == [delegation]
    assert sample.member in service.candidates(sample.headman)
    sample.clock.moment = delegation.valid_until - timedelta(microseconds=1)
    assert sample.services.attendance.is_responsible(sample.member)
    sample.clock.moment = delegation.valid_until
    assert not sample.services.attendance.is_responsible(sample.member)
    assert service.active_for(sample.member) == []
    service.notify_expired(sample.clock.now())
    service.notify_expired(sample.clock.now())
    assert Notification.objects.filter(type=NotificationType.DELEGATION_EXPIRED).count() == 1


@pytest.mark.parametrize("grantor,delegate", [("member", "headman"), ("outsider", "member"),
    ("headman", "headman"), ("headman", "deputy"), ("headman", "outsider")])
def test_invalid_assignment_roles_and_groups(sample, grantor, delegate):
    with pytest.raises(AccessDeniedError):
        sample.services.delegation.assign(getattr(sample, grantor), getattr(sample, delegate))


def test_duplicate_and_forward_delegation_are_forbidden(sample):
    service = sample.services.delegation
    service.assign(sample.headman, sample.member)
    with pytest.raises(AccessDeniedError):
        service.assign(sample.deputy, sample.member)
    with pytest.raises(AccessDeniedError):
        service.assign(sample.member, sample.headman)
    assert service.candidates(sample.member) == []


def test_revoke_requires_own_group_headman_and_is_idempotent_error(sample):
    service = sample.services.delegation
    delegation = service.assign(sample.headman, sample.member)
    with pytest.raises(AccessDeniedError):
        service.revoke(sample.outsider, delegation.pk)
    service.revoke(sample.deputy, delegation.pk)
    assert not sample.services.attendance.is_responsible(sample.member)
    with pytest.raises(InvalidChangeError):
        service.revoke(sample.headman, delegation.pk)
    service.notify_expired(next_midnight(sample.now))
    assert not Notification.objects.filter(type=NotificationType.DELEGATION_EXPIRED).exists()


def test_inactive_or_unknown_delegate_is_rejected(sample):
    sample.member.user.is_active = False
    sample.member.user.save(update_fields=["is_active"])
    with pytest.raises(AccessDeniedError):
        sample.services.delegation.assign(sample.headman, sample.member)
    with pytest.raises(InvalidChangeError):
        sample.services.delegation.assign_by_id(sample.headman, sample.outsider.pk)
    with pytest.raises(InvalidChangeError):
        sample.services.delegation.revoke(sample.headman, 999999)
