"""Одноразовая привязка личного чата Telegram к учетной записи сайта."""
from datetime import timedelta
import secrets

from django.db import IntegrityError, transaction

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import LinkToken, Student, TelegramLink

from .interfaces import IClock

LINK_TOKEN_TTL = timedelta(minutes=15)


class TelegramLinkService:
    def __init__(self, clock: IClock):
        self.clock = clock

    def create_link_token(self, student: Student) -> str:
        now = self.clock.now()
        with transaction.atomic():
            Student.objects.select_for_update().get(pk=student.pk, user__is_active=True)
            LinkToken.objects.filter(student=student, used_at__isnull=True).update(used_at=now)
            token = secrets.token_urlsafe(32)
            LinkToken.objects.create(student=student, token=token, expires_at=now + LINK_TOKEN_TTL)
        return token

    def bind(self, token: str, chat_id: str) -> TelegramLink:
        if not str(chat_id).isdigit() or int(chat_id) <= 0:
            raise InvalidChangeError("Привязка доступна только в личном чате с ботом")
        now = self.clock.now()
        try:
            with transaction.atomic():
                candidate = LinkToken.objects.filter(token=token).first()
                if candidate is None:
                    raise InvalidChangeError("Ссылка недействительна. Получите новую на сайте")
                Student.objects.select_for_update().get(pk=candidate.student_id, user__is_active=True)
                claimed = LinkToken.objects.filter(pk=candidate.pk, used_at__isnull=True,
                                                   expires_at__gt=now).update(used_at=now)
                if not claimed:
                    raise InvalidChangeError("Ссылка истекла или уже использована. Получите новую на сайте")
                if TelegramLink.objects.filter(chat_id=str(chat_id)).exclude(student_id=candidate.student_id).exists():
                    raise InvalidChangeError("Этот Telegram уже привязан к другому аккаунту. Сначала отвяжите его на сайте")
                link, _ = TelegramLink.objects.update_or_create(student_id=candidate.student_id,
                    defaults={"chat_id": str(chat_id), "linked_at": now, "notifications_enabled": True})
                return link
        except (IntegrityError, Student.DoesNotExist) as error:
            raise InvalidChangeError("Не удалось привязать аккаунт. Получите новую ссылку на сайте") from error

    def get_link(self, student: Student) -> TelegramLink | None:
        return TelegramLink.objects.filter(student=student).first()

    def student_for_chat(self, chat_id: str) -> Student:
        link = TelegramLink.objects.filter(chat_id=str(chat_id), student__user__is_active=True).select_related(
            "student__user", "student__group").first()
        if link is None:
            raise AccessDeniedError("Привяжите Telegram в личном кабинете сайта")
        return link.student

    def unlink(self, student: Student) -> None:
        with transaction.atomic():
            Student.objects.select_for_update().get(pk=student.pk)
            TelegramLink.objects.filter(student=student).delete()
            LinkToken.objects.filter(student=student, used_at__isnull=True).update(used_at=self.clock.now())
            student.notifications.filter(sent_at__isnull=True).update(skipped=True)

    def unlink_chat(self, chat_id: str) -> None:
        """Выход из бота: отвязать только тот чат, который запросил выход."""
        student_id = TelegramLink.objects.filter(chat_id=str(chat_id)).values_list("student_id", flat=True).first()
        if student_id is None:
            return
        with transaction.atomic():
            student = Student.objects.select_for_update().filter(pk=student_id).first()
            if student is not None and TelegramLink.objects.filter(student=student, chat_id=str(chat_id)).exists():
                self.unlink(student)

    def set_notifications(self, student: Student, enabled: bool) -> None:
        with transaction.atomic():
            if not TelegramLink.objects.filter(student=student).update(notifications_enabled=enabled):
                raise InvalidChangeError("Сначала привяжите Telegram")
            if not enabled:
                student.notifications.filter(sent_at__isnull=True).update(skipped=True)
