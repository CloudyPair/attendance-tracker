from attendance.models import NotificationType, Student

from .interfaces import IClock, INotificationChannel


class NullChannel(INotificationChannel):
    """Канал по умолчанию, пока нет бота: ничего не отправляет."""

    def send(self, chat_id: str, text: str) -> bool:
        return False


class NotificationService:
    def __init__(self, clock: IClock, channel: INotificationChannel):
        self.clock = clock
        self.channel = channel

    def notify(self, recipient: Student, type: NotificationType, text: str) -> None:
        """1. INSERT Notification.
        2. Если у получателя есть TelegramLink и notifications_enabled -
           channel.send(chat_id, text); при успехе заполнить sent_at.
        Ошибка отправки не должна откатывать основное действие (вызывать после commit).
        """
        raise NotImplementedError("ЛР4")

    def notify_headmen(self, group_id: int, type: NotificationType, text: str) -> None:
        """notify() для старосты и заместителя группы."""
        raise NotImplementedError("ЛР4")
