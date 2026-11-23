"""Причины пропусков, личные вложения и рассмотрение споров."""
from django.db import IntegrityError, transaction

from attendance.errors import AccessDeniedError, InvalidChangeError
from attendance.models import (AbsenceReason, AttendanceRecord, AttendanceStatus, ChangeSource,
                               Dispute, DisputeStatus, Lesson, NotificationType, Student, Teacher)

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

    @staticmethod
    def _text(value, label):
        value = (value or "").strip()
        if not value or len(value) > 2000:
            raise InvalidChangeError(f"{label}: введите от 1 до 2000 символов")
        return value

    def own_record(self, student: Student, record_id: int) -> AttendanceRecord:
        record = AttendanceRecord.objects.select_related("lesson__course__subject", "absence_reason").filter(
            pk=record_id, student=student).first()
        if record is None:
            raise AccessDeniedError("Эта отметка вам недоступна")
        if record.status != AttendanceStatus.ABSENT:
            raise InvalidChangeError("Оспорить можно только отметку «Не был»")
        return record

    def absences(self, student: Student):
        return list(AttendanceRecord.objects.filter(student=student, status=AttendanceStatus.ABSENT)
            .select_related("lesson__course__subject", "absence_reason")
            .prefetch_related("disputes").order_by("-lesson__start_at", "-pk"))

    def set_absence_reason(self, student: Student, record_id: int, text: str, attachment=None) -> None:
        text = self._text(text, "Причина")
        if attachment is not None and attachment.size > 5 * 1024 * 1024:
            raise InvalidChangeError("Размер вложения не должен превышать 5 МБ")
        with transaction.atomic():
            record = self.own_record(student, record_id)
            AttendanceRecord.objects.select_for_update().get(pk=record.pk)
            if not AttendanceRecord.objects.filter(pk=record.pk, status=AttendanceStatus.ABSENT).exists():
                raise InvalidChangeError("Отметка уже изменена. Обновите страницу")
            reason, _ = AbsenceReason.objects.get_or_create(record=record, defaults={"text": text})
            reason.text = text
            if attachment is not None:
                reason.attachment = attachment
            reason.save()

    def attachment_for(self, user, reason_id: int):
        reason = AbsenceReason.objects.select_related("record__lesson__course", "record__student").get(pk=reason_id)
        student = getattr(user, "student", None)
        teacher = getattr(user, "teacher", None)
        permitted = student is not None and reason.record.student_id == student.pk
        permitted = permitted or (teacher is not None and self.policy.can_view_course(
            teacher, reason.record.lesson.course))
        if not permitted:
            raise AccessDeniedError("Вложение доступно студенту и преподавателю предмета")
        if not reason.attachment:
            raise InvalidChangeError("Вложение отсутствует")
        return reason.attachment

    def attachment_for_dispute(self, user, dispute_id: int):
        dispute = Dispute.objects.select_related("record__lesson__course", "record__student").get(pk=dispute_id)
        student = getattr(user, "student", None)
        teacher = getattr(user, "teacher", None)
        permitted = student is not None and dispute.record.student_id == student.pk
        permitted = permitted or (teacher is not None and self.policy.can_view_course(
            teacher, dispute.record.lesson.course))
        if not permitted:
            raise AccessDeniedError("Документ доступен студенту и преподавателю предмета")
        if not dispute.attachment:
            raise InvalidChangeError("Вложение отсутствует")
        return dispute.attachment

    def create(self, student: Student, record_id: int, comment: str, attachment=None) -> Dispute:
        comment = self._text(comment, "Комментарий")
        if attachment is not None and attachment.size > 5 * 1024 * 1024:
            raise InvalidChangeError("Размер вложения не должен превышать 5 МБ")
        try:
            with transaction.atomic():
                record = self.own_record(student, record_id)
                Lesson.objects.select_for_update().get(pk=record.lesson_id)
                record = self.own_record(student, record_id)
                if not record.lesson.course.teachers.filter(user__is_active=True).exists():
                    raise InvalidChangeError("По этому предмету еще не назначен преподаватель. "
                                             "Попросите администратора назначить его для рассмотрения заявки")
                if record.disputes.filter(status=DisputeStatus.OPEN).exists():
                    raise InvalidChangeError("По этой отметке уже есть открытый спор")
                previous = getattr(record, "absence_reason", None)
                evidence = attachment if attachment is not None else (
                    previous.attachment.name if previous and previous.attachment else "")
                dispute = Dispute.objects.create(record=record, comment=comment,
                    attachment=evidence, created_at=self.clock.now())
                return dispute
        except IntegrityError as error:
            raise InvalidChangeError("По этой отметке уже есть открытый спор") from error

    def list_for(self, actor: Student | Teacher):
        rows = Dispute.objects.all()
        if isinstance(actor, Teacher):
            rows = rows.filter(record__lesson__course__teachers=actor)
        elif isinstance(actor, Student):
            rows = rows.filter(record__student=actor)
        else:
            raise AccessDeniedError("Нужен профиль студента или преподавателя")
        return list(rows.select_related("record__student__user", "record__student__group",
            "record__lesson__course__subject", "resolved_by").order_by("-created_at", "-pk"))

    def can_resolve(self, teacher: Teacher, dispute: Dispute) -> bool:
        return dispute.status == DisputeStatus.OPEN and self.policy.can_resolve_dispute(teacher, dispute)

    def can_delete(self, teacher: Teacher, dispute: Dispute) -> bool:
        return isinstance(teacher, Teacher) and self.policy.can_view_course(teacher, dispute.record.lesson.course)

    def delete(self, teacher: Teacher, dispute_id: int) -> None:
        with transaction.atomic():
            candidate = Dispute.objects.filter(pk=dispute_id).values("record__lesson_id").first()
            if candidate is None:
                raise InvalidChangeError("Спор уже удален или не найден")
            # Такой же порядок блокировок, как при рассмотрении и исправлении отметки.
            Lesson.objects.select_for_update().get(pk=candidate["record__lesson_id"])
            dispute = Dispute.objects.select_for_update().select_related("record__lesson__course").filter(
                pk=dispute_id).first()
            if dispute is None:
                raise InvalidChangeError("Спор уже удален или не найден")
            if not self.can_delete(teacher, dispute):
                raise AccessDeniedError("Удалять спор может только преподаватель этого предмета")
            dispute.delete()

    def resolve(self, resolver: Teacher, dispute_id: int, fix: bool, comment: str = "") -> None:
        comment = (comment or "").strip()
        if len(comment) > 2000:
            raise InvalidChangeError("Комментарий не должен превышать 2000 символов")
        with transaction.atomic():
            candidate = Dispute.objects.filter(pk=dispute_id).values("record__lesson_id").first()
            if candidate is None:
                raise InvalidChangeError("Спор не найден")
            # Единый порядок блокировок с AttendanceService: занятие, затем запись и спор.
            Lesson.objects.select_for_update().get(pk=candidate["record__lesson_id"])
            dispute = Dispute.objects.select_for_update().select_related(
                "record__student__user", "record__student__group").filter(pk=dispute_id).first()
            if dispute is None:
                raise InvalidChangeError("Спор уже удален или не найден")
            if not self.policy.can_resolve_dispute(resolver, dispute):
                raise AccessDeniedError("Решение принимает преподаватель этого предмета")
            if dispute.status != DisputeStatus.OPEN:
                raise InvalidChangeError("Спор уже рассмотрен")
            if fix and dispute.record.status != AttendanceStatus.PRESENT:
                self.attendance.correct_record(resolver, dispute.record_id, AttendanceStatus.PRESENT,
                    f"Спор №{dispute.pk}", ChangeSource.DISPUTE)
            dispute.resolve(fix, resolver, comment, self.clock.now())
            result = "Отметка исправлена на «Был»." if fix else f"Отклонен: {comment}"
            self.notifications.notify(dispute.record.student, NotificationType.DISPUTE_RESOLVED,
                                      f"Спор №{dispute.pk} рассмотрен. {result}")
