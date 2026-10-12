"""Временная замена старосты (sequence_delegation.puml)."""
from datetime import datetime

from attendance.models import Delegation, Student

from .interfaces import IClock
from .notifications import NotificationService
from .policy import AccessPolicy


class DelegationService:
    def __init__(self, clock: IClock, policy: AccessPolicy, notifications: NotificationService):
        self.clock = clock
        self.policy = policy
        self.notifications = notifications

    def assign(self, grantor: Student, delegate: Student) -> Delegation:
        """1. policy.can_assign_delegate(grantor, delegate, now), иначе AccessDeniedError.
        2. INSERT Delegation(granted_at = now, valid_until = next_midnight(now)).
        3. notifications.notify(delegate, DELEGATION_GRANTED, ...).
        """
        raise NotImplementedError("ЛР4")

    def revoke(self, grantor: Student, delegation_id: int) -> None:
        """delegation.revoke(grantor, now) -> UPDATE revoked_at;
        notify(delegate, DELEGATION_REVOKED)."""
        raise NotImplementedError("ЛР4")

    def notify_expired(self, now: datetime) -> None:
        """Запускается планировщиком после 00:00: уведомить делегатов, чья замена истекла.
        Права снимаются сами (is_active сравнивает с valid_until), здесь только уведомления.
        """
        raise NotImplementedError("ЛР4")
