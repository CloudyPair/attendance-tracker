"""Временная замена старосты до начала следующих суток."""
from datetime import datetime

from django.db import transaction

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import Delegation, GroupRole, NotificationType, Student
from attendance.timeutils import next_midnight

from .interfaces import IClock
from .notifications import NotificationService
from .policy import AccessPolicy


class DelegationService:
    def __init__(self, clock: IClock, policy: AccessPolicy, notifications: NotificationService):
        self.clock = clock
        self.policy = policy
        self.notifications = notifications

    def candidates(self, grantor: Student):
        if not grantor.is_headman_or_deputy():
            return []
        return list(Student.objects.filter(group_id=grantor.group_id, role=GroupRole.MEMBER,
            user__is_active=True).select_related("user", "group").order_by("user__last_name", "pk"))

    def active_for(self, student: Student):
        rows = Delegation.objects.filter(revoked_at__isnull=True, granted_at__lte=self.clock.now(),
            valid_until__gt=self.clock.now()).select_related("delegate__user", "granted_by__user")
        if student.is_headman_or_deputy():
            return list(rows.filter(delegate__group_id=student.group_id))
        return list(rows.filter(delegate=student))

    def assign(self, grantor: Student, delegate: Student) -> Delegation:
        now = self.clock.now()
        with transaction.atomic():
            locked = {s.pk: s for s in Student.objects.select_for_update().filter(
                pk__in=[grantor.pk, delegate.pk]).select_related("group", "user").order_by("pk")}
            grantor, delegate = locked[grantor.pk], locked[delegate.pk]
            if not delegate.user.is_active or not self.policy.can_assign_delegate(grantor, delegate, now):
                raise AccessDeniedError("Выберите студента своей группы без действующей замены")
            delegation = Delegation.objects.create(granted_by=grantor, delegate=delegate,
                granted_at=now, valid_until=next_midnight(now))
            self.notifications.notify(delegate, NotificationType.DELEGATION_GRANTED,
                "Вы назначены временной заменой старосты до 00:00. Можно отмечать занятия своей группы.")
            return delegation

    def assign_by_id(self, grantor: Student, delegate_id: int) -> Delegation:
        delegate = Student.objects.filter(pk=delegate_id, group_id=grantor.group_id).first()
        if delegate is None:
            raise InvalidChangeError("Студент не найден в вашей группе")
        return self.assign(grantor, delegate)

    def revoke(self, grantor: Student, delegation_id: int) -> None:
        with transaction.atomic():
            delegation = Delegation.objects.select_for_update().select_related("delegate__group").filter(
                pk=delegation_id).first()
            if delegation is None:
                raise InvalidChangeError("Замена не найдена")
            delegation.revoke(grantor, self.clock.now())
            self.notifications.notify(delegation.delegate, NotificationType.DELEGATION_REVOKED,
                                      "Ваша временная замена старосты отозвана.")

    def notify_expired(self, now: datetime) -> None:
        ids = list(Delegation.objects.filter(valid_until__lte=now, revoked_at__isnull=True,
            expiry_notified_at__isnull=True).values_list("pk", flat=True))
        for pk in ids:
            with transaction.atomic():
                if not Delegation.objects.filter(pk=pk, expiry_notified_at__isnull=True,
                        revoked_at__isnull=True).update(expiry_notified_at=now):
                    continue
                delegation = Delegation.objects.select_related("delegate").get(pk=pk)
                self.notifications.notify(delegation.delegate, NotificationType.DELEGATION_EXPIRED,
                                          "Срок временной замены старосты закончился.")