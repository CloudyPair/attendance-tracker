"""Уведомления с очередью в БД: ошибки Telegram не отменяют учебные действия."""
from datetime import timedelta
import logging

from django.db import transaction
from django.db.models import F, Q

from attendance.models import GroupRole, Notification, NotificationType, Student, TelegramLink

from .interfaces import IClock, INotificationChannel

logger = logging.getLogger(__name__)


class NullChannel(INotificationChannel):
    def send(self, chat_id: str, text: str) -> bool:
        return False


class NotificationService:
    MAX_ATTEMPTS = 5

    def __init__(self, clock: IClock, channel: INotificationChannel):
        self.clock = clock
        self.channel = channel

    def notify(self, recipient: Student, type: NotificationType, text: str) -> None:
        enabled = TelegramLink.objects.filter(student=recipient, notifications_enabled=True,
                                              student__user__is_active=True).exists()
        notification = Notification.objects.create(recipient=recipient, type=type, text=text,
            created_at=self.clock.now(), skipped=not enabled)
        if enabled:
            transaction.on_commit(lambda: self.deliver(notification.pk), robust=True)

    def deliver(self, notification_id: int) -> None:
        now = self.clock.now()
        pending = Notification.objects.filter(pk=notification_id, sent_at__isnull=True,
            skipped=False, attempts__lt=self.MAX_ATTEMPTS).filter(
            Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lte=now - timedelta(minutes=1)))
        item = pending.first()
        if item is None:
            return
        link = TelegramLink.objects.filter(student_id=item.recipient_id, notifications_enabled=True,
            student__user__is_active=True, linked_at__lte=item.created_at).first()
        if link is None:
            pending.update(skipped=True)
            return
        # Атомарное получение задачи: веб и фоновый обработчик не отправляют ее одновременно.
        if not pending.filter(attempts=item.attempts, last_attempt_at=item.last_attempt_at).update(
                attempts=F("attempts") + 1, last_attempt_at=now):
            return
        try:
            sent = self.channel.send(link.chat_id, item.text)
        except Exception:
            # Исключения HTTP могут содержать URL с токеном.
            logger.warning("Ошибка доставки уведомления %s", item.pk)
            sent = False
        if sent:
            Notification.objects.filter(pk=item.pk).update(sent_at=self.clock.now())

    def retry_pending(self, limit: int = 100) -> None:
        ids = list(Notification.objects.filter(sent_at__isnull=True, skipped=False,
            attempts__lt=self.MAX_ATTEMPTS).filter(Q(last_attempt_at__isnull=True) |
            Q(last_attempt_at__lte=self.clock.now() - timedelta(minutes=1)))
            .order_by("created_at").values_list("pk", flat=True)[:limit])
        for pk in ids:
            self.deliver(pk)

    def notify_headmen(self, group_id: int, type: NotificationType, text: str) -> None:
        for student in Student.objects.filter(group_id=group_id,
                role__in=[GroupRole.HEADMAN, GroupRole.DEPUTY], user__is_active=True):
            self.notify(student, type, text)