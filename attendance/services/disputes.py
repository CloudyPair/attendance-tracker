"""Причина пропуска и оспаривание отметки (sequence_dispute.puml, activity_dispute.puml)."""
from attendance.models import Dispute, Student

from .attendance import AttendanceService
from .interfaces import IClock
from .notifications import NotificationService
from .policy import AccessPolicy


class DisputeService:
    def __init__(self, clock: IClock, policy: AccessPolicy,
                 attendance: AttendanceService, notifications: NotificationService):
        self.clock = clock
        self.policy = policy
        self.attendance = attendance
        self.notifications = notifications

    def set_absence_reason(self, student: Student, record_id: int, text: str) -> None:
        """Запись принадлежит студенту и в статусе ABSENT -> INSERT/UPDATE AbsenceReason."""
        raise NotImplementedError("ЛР4")

    def create(self, student: Student, record_id: int, comment: str) -> Dispute:
        """1. Запись студента, статус ABSENT, нет открытого спора
           (дубль ловит и ограничение one_open_dispute_per_record).
        2. INSERT Dispute(OPEN).
        3. notifications.notify_headmen(group, DISPUTE_CREATED, ...).
        """
        raise NotImplementedError("ЛР4")

    def resolve(self, resolver: Student, dispute_id: int, fix: bool, comment: str) -> None:
        """1. policy.can_resolve_dispute, иначе AccessDeniedError.
        2. В транзакции: dispute.resolve(...);
           fix -> attendance.correct_record(..., PRESENT, «Спор №N», DISPUTE).
        3. notifications.notify(студент, DISPUTE_RESOLVED, ...).
        """
        raise NotImplementedError("ЛР4")
