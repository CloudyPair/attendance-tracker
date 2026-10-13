"""Модели предметной области (UML/class_domain.puml).

Каждая модель - это таблица в БД и класс диаграммы. Методы моделей проверяют
правила своего объекта и сами сохраняют изменения. Кто имеет право на
действие, проверяет AccessPolicy (attendance/services).

Время передаётся параметром `now`, границы суток считаются по местному
времени (attendance/timeutils.py).
"""
from datetime import datetime

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from .errors import AccessDeniedError, InvalidChangeError, ReasonRequiredError
from .timeutils import day_start, next_midnight


# Перечисления

class GroupRole(models.TextChoices):
    MEMBER = "MEMBER", "Студент"
    HEADMAN = "HEADMAN", "Староста"
    DEPUTY = "DEPUTY", "Заместитель старосты"


class LessonType(models.TextChoices):
    LECTURE = "LECTURE", "Лекция"
    SEMINAR = "SEMINAR", "Семинар"
    LAB = "LAB", "Лабораторная"


class AttendanceStatus(models.TextChoices):
    NOT_MARKED = "NOT_MARKED", "Не отмечено"
    PRESENT = "PRESENT", "Присутствовал"
    ABSENT = "ABSENT", "Отсутствовал"


class DisputeStatus(models.TextChoices):
    OPEN = "OPEN", "Открыт"
    FIXED = "FIXED", "Исправлено"
    REJECTED = "REJECTED", "Отклонено"


class ChangeSource(models.TextChoices):
    MARKING = "MARKING", "Отметка"
    EDIT = "EDIT", "Правка"
    DISPUTE = "DISPUTE", "Спор"


class NotificationType(models.TextChoices):
    DISPUTE_CREATED = "DISPUTE_CREATED", "Создан спор"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED", "Спор рассмотрен"
    DELEGATION_GRANTED = "DELEGATION_GRANTED", "Назначена замена"
    DELEGATION_REVOKED = "DELEGATION_REVOKED", "Замена отозвана"
    THRESHOLD_WARNING = "THRESHOLD_WARNING", "Приближение к порогу"


# Пользователи и учебная структура

class User(AbstractUser):
    """Учётная запись. Роль задаётся профилем Student или Teacher."""

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.username


class Group(models.Model):
    name = models.CharField("название", max_length=50, unique=True)

    class Meta:
        verbose_name = "группа"
        verbose_name_plural = "группы"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student")
    group = models.ForeignKey(
        Group, on_delete=models.PROTECT,
        related_name="students", verbose_name="группа",
    )
    role = models.CharField(
        "роль в группе", max_length=10,
        choices=GroupRole.choices, default=GroupRole.MEMBER,
    )

    class Meta:
        verbose_name = "студент"
        verbose_name_plural = "студенты"
        constraints = [
            # В группе не больше одного старосты и одного заместителя
            models.UniqueConstraint(fields=["group"], condition=Q(role=GroupRole.HEADMAN),
                                    name="one_headman_per_group"),
            models.UniqueConstraint(fields=["group"], condition=Q(role=GroupRole.DEPUTY),
                                    name="one_deputy_per_group"),
        ]

    def __str__(self):
        return f"{self.user.full_name} ({self.group})"

    def is_headman_or_deputy(self) -> bool:
        return self.role in (GroupRole.HEADMAN, GroupRole.DEPUTY)

    def belongs_to(self, group: "Group | None") -> bool:
        return group is not None and self.group_id == group.pk

    def has_active_delegation(self, now: datetime) -> bool:
        for delegation in self.delegations.all():
            if delegation.is_active(now):
                return True
        return False


class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="teacher")

    class Meta:
        verbose_name = "преподаватель"
        verbose_name_plural = "преподаватели"

    def __str__(self):
        return self.user.full_name


class Subject(models.Model):
    name = models.CharField("название", max_length=255, unique=True)

    class Meta:
        verbose_name = "предмет"
        verbose_name_plural = "предметы"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Course(models.Model):
    """Предмет у конкретной группы в семестре."""

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE,
        related_name="courses", verbose_name="группа",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT,
        related_name="courses", verbose_name="предмет",
    )
    semester = models.CharField("семестр", max_length=20)
    threshold_percent = models.PositiveSmallIntegerField(
        "порог посещаемости, %", default=50,
        validators=[MaxValueValidator(100)],
    )
    teachers = models.ManyToManyField(Teacher, related_name="courses", verbose_name="преподаватели")

    class Meta:
        verbose_name = "курс"
        verbose_name_plural = "курсы"
        constraints = [
            models.UniqueConstraint(fields=["group", "subject", "semester"], name="unique_course"),
            models.CheckConstraint(condition=Q(threshold_percent__lte=100), name="threshold_0_100"),
        ]

    def __str__(self):
        return f"{self.subject} - {self.group}, {self.semester}"

    def set_threshold(self, percent: int) -> None:
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            raise ValueError("Порог должен быть целым числом от 0 до 100")

        self.threshold_percent = percent
        self.save(update_fields=["threshold_percent"])


class Lesson(models.Model):
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name="lessons", verbose_name="курс",
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lessons", verbose_name="преподаватель",
    )
    # UID события из .ics + дата; пусто, если занятие заведено вручную
    external_uid = models.CharField(
        "внешний UID", max_length=255,
        unique=True, null=True, blank=True,
    )
    start_at = models.DateTimeField("начало")
    end_at = models.DateTimeField("окончание")
    type = models.CharField("тип", max_length=10, choices=LessonType.choices)
    room = models.CharField("аудитория", max_length=50, blank=True)

    class Meta:
        verbose_name = "занятие"
        verbose_name_plural = "занятия"
        ordering = ["start_at"]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")),
                                   name="lesson_end_after_start"),
        ]

    def __str__(self):
        start = timezone.localtime(self.start_at)
        return f"{self.course.subject}, {self.get_type_display()}, {start:%d.%m.%Y %H:%M}"

    def window_opens_at(self) -> datetime:
        """Отмечать можно с 00:00 дня занятия..."""
        return day_start(self.start_at)

    def edit_deadline(self) -> datetime:
        """...и до 00:00 следующего дня (не включительно)."""
        return next_midnight(self.start_at)

    def is_marking_window_open(self, now: datetime) -> bool:
        return self.window_opens_at() <= now < self.edit_deadline()

    def has_started(self, now: datetime) -> bool:
        return now >= self.start_at


# Посещаемость

class AttendanceRecord(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name="records", verbose_name="занятие",
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE,
        related_name="records", verbose_name="студент",
    )
    status = models.CharField(
        "статус", max_length=10,
        choices=AttendanceStatus.choices, default=AttendanceStatus.NOT_MARKED,
    )
    marked_by = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="отметил",
    )
    marked_at = models.DateTimeField("время первой отметки", null=True, blank=True)
    last_changed_at = models.DateTimeField("время последнего изменения", null=True, blank=True)

    class Meta:
        verbose_name = "отметка"
        verbose_name_plural = "отметки"
        constraints = [
            # ТЗ 5.2: одно занятие нельзя отметить у студента дважды
            models.UniqueConstraint(fields=["lesson", "student"],
                                    name="one_record_per_lesson_student"),
        ]

    def __str__(self):
        return f"{self.student} - {self.lesson}: {self.get_status_display()}"

    def change(self, new_status: str, by: "Student", reason: str, now: datetime,
               source: str | None = None) -> "AttendanceChange":
        """Сменить статус и записать изменение в историю.

        Первая отметка (из NOT_MARKED) сохраняется без причины.
        Для любой следующей правки причина обязательна.
        """
        if new_status == AttendanceStatus.NOT_MARKED:
            raise InvalidChangeError("Отметку нельзя вернуть в «не отмечено»")
        if new_status == self.status:
            raise InvalidChangeError("Статус не меняется")

        reason = (reason or "").strip()
        is_first_mark = self.status == AttendanceStatus.NOT_MARKED

        if is_first_mark:
            source = ChangeSource.MARKING
        elif not reason:
            raise ReasonRequiredError("Для правки сохранённой отметки нужна причина")
        else:
            source = source or ChangeSource.EDIT

        entry = AttendanceChange(
            record=self,
            old_status=self.status,
            new_status=new_status,
            changed_by=by,
            changed_at=now,
            reason=reason,
            source=source,
        )

        self.status = new_status
        self.last_changed_at = now
        if is_first_mark:
            self.marked_by = by
            self.marked_at = now

        # Отметка и запись в истории сохраняются вместе или не сохраняются вовсе
        with transaction.atomic():
            self.save()
            entry.save()
        return entry


class AttendanceChange(models.Model):
    record = models.ForeignKey(
        AttendanceRecord, on_delete=models.CASCADE,
        related_name="changes", verbose_name="отметка",
    )
    old_status = models.CharField("было", max_length=10, choices=AttendanceStatus.choices)
    new_status = models.CharField("стало", max_length=10, choices=AttendanceStatus.choices)
    changed_by = models.ForeignKey(
        Student, on_delete=models.PROTECT,
        related_name="+", verbose_name="изменил",
    )
    changed_at = models.DateTimeField("когда", default=timezone.now)
    reason = models.TextField("причина", blank=True)
    source = models.CharField("источник", max_length=10, choices=ChangeSource.choices)

    class Meta:
        verbose_name = "изменение отметки"
        verbose_name_plural = "история изменений"
        ordering = ["changed_at"]

    def __str__(self):
        return f"{self.old_status} → {self.new_status} ({self.changed_at:%d.%m.%Y %H:%M})"


class AbsenceReason(models.Model):
    record = models.OneToOneField(
        AttendanceRecord, on_delete=models.CASCADE,
        related_name="absence_reason", verbose_name="отметка",
    )
    text = models.TextField("причина")
    attachment = models.FileField("вложение", upload_to="absence/%Y/%m/", blank=True)
    created_at = models.DateTimeField("создана", default=timezone.now)

    class Meta:
        verbose_name = "причина пропуска"
        verbose_name_plural = "причины пропусков"

    def __str__(self):
        return self.text[:50]


class Dispute(models.Model):
    record = models.ForeignKey(
        AttendanceRecord, on_delete=models.CASCADE,
        related_name="disputes", verbose_name="отметка",
    )
    comment = models.TextField("комментарий студента")
    status = models.CharField(
        "статус", max_length=10,
        choices=DisputeStatus.choices, default=DisputeStatus.OPEN,
    )
    created_at = models.DateTimeField("создан", default=timezone.now)
    resolved_at = models.DateTimeField("рассмотрен", null=True, blank=True)
    resolved_by = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="рассмотрел",
    )
    resolution_comment = models.TextField("комментарий к решению", blank=True)

    class Meta:
        verbose_name = "спор"
        verbose_name_plural = "споры"
        constraints = [
            # По одной отметке не больше одного открытого спора
            models.UniqueConstraint(fields=["record"], condition=Q(status=DisputeStatus.OPEN),
                                    name="one_open_dispute_per_record"),
        ]

    def __str__(self):
        return f"Спор №{self.pk}: {self.get_status_display()}"

    def resolve(self, fix: bool, by: "Student", comment: str, now: datetime) -> None:
        """Зафиксировать решение. Саму отметку исправляет AttendanceService."""
        if self.status != DisputeStatus.OPEN:
            raise InvalidChangeError("Спор уже рассмотрен")

        comment = (comment or "").strip()
        if not fix and not comment:
            raise ReasonRequiredError("При отклонении спора нужен комментарий")

        self.status = DisputeStatus.FIXED if fix else DisputeStatus.REJECTED
        self.resolved_by = by
        self.resolved_at = now
        self.resolution_comment = comment
        self.save()


# Замена старосты

class Delegation(models.Model):
    granted_by = models.ForeignKey(
        Student, on_delete=models.PROTECT,
        related_name="granted_delegations", verbose_name="назначил",
    )
    delegate = models.ForeignKey(
        Student, on_delete=models.CASCADE,
        related_name="delegations", verbose_name="замена",
    )
    granted_at = models.DateTimeField("назначена", default=timezone.now)
    valid_until = models.DateTimeField("действует до")
    revoked_at = models.DateTimeField("отозвана", null=True, blank=True)

    class Meta:
        verbose_name = "замена старосты"
        verbose_name_plural = "замены старосты"
        constraints = [
            models.CheckConstraint(condition=Q(valid_until__gt=F("granted_at")),
                                   name="delegation_valid_period"),
            models.CheckConstraint(condition=~Q(granted_by=F("delegate")),
                                   name="delegation_not_self"),
        ]

    def __str__(self):
        return f"{self.delegate} до {timezone.localtime(self.valid_until):%d.%m %H:%M}"

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.granted_at <= now < self.valid_until

    def revoke(self, by: "Student", now: datetime) -> None:
        if not (by.is_headman_or_deputy() and by.belongs_to(self.delegate.group)):
            raise AccessDeniedError("Отозвать замену может только староста или заместитель группы")
        if not self.is_active(now):
            raise InvalidChangeError("Замена уже не действует")

        self.revoked_at = now
        self.save(update_fields=["revoked_at"])


# Telegram и уведомления

class TelegramLink(models.Model):
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name="telegram_link")
    chat_id = models.CharField("chat id", max_length=64, unique=True)
    linked_at = models.DateTimeField("привязан", default=timezone.now)
    notifications_enabled = models.BooleanField("уведомления включены", default=True)

    class Meta:
        verbose_name = "привязка Telegram"
        verbose_name_plural = "привязки Telegram"

    def __str__(self):
        return f"{self.student} → {self.chat_id}"


class LinkToken(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="link_tokens")
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField("истекает")
    used_at = models.DateTimeField("использован", null=True, blank=True)

    class Meta:
        verbose_name = "токен привязки"
        verbose_name_plural = "токены привязки"

    def __str__(self):
        return f"токен для {self.student}"

    def is_valid(self, now: datetime) -> bool:
        return self.used_at is None and now < self.expires_at


class Notification(models.Model):
    recipient = models.ForeignKey(
        Student, on_delete=models.CASCADE,
        related_name="notifications", verbose_name="получатель",
    )
    type = models.CharField("тип", max_length=20, choices=NotificationType.choices)
    text = models.TextField("текст")
    created_at = models.DateTimeField("создано", default=timezone.now)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} → {self.recipient}"
