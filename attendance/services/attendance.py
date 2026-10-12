"""Отметка и правка посещаемости (sequence_marking.puml, activity_marking.puml)."""
from attendance.models import AttendanceRecord, AttendanceStatus, ChangeSource, Lesson, Student

from .interfaces import IClock
from .notifications import NotificationService
from .policy import AccessPolicy
from .statistics import StatisticsService


class AttendanceService:
    def __init__(self, clock: IClock, policy: AccessPolicy,
                 statistics: StatisticsService, notifications: NotificationService):
        self.clock = clock
        self.policy = policy
        self.statistics = statistics
        self.notifications = notifications

    def open_lesson(self, user: Student, lesson_id: int) -> list[AttendanceRecord]:
        """1. policy.can_mark(user, lesson, now), иначе AccessDeniedError.
        2. get_or_create AttendanceRecord(NOT_MARKED) для каждого студента группы.
        3. Вернуть записи, упорядоченные по фамилии.
        """
        raise NotImplementedError("ЛР4")

    def save_marks(self, user: Student, lesson_id: int,
                   marks: dict[int, AttendanceStatus], reason: str) -> None:
        """marks: student_id -> PRESENT/ABSENT; неизменённые записи пропускаются.

        1. can_mark для занятия; can_edit для уже отмеченных записей.
        2. Запомнить уровни предупреждения затронутых студентов (statistics).
        3. transaction.atomic + select_for_update записей:
           record.change(...) -> UPDATE AttendanceRecord + INSERT AttendanceChange.
           Ошибка/IntegrityError -> откат, «Данные изменились, обновите страницу».
        4. После commit: пересчитать уровни; если ухудшился -
           notifications.notify(student, THRESHOLD_WARNING, ...).
        """
        raise NotImplementedError("ЛР4")

    def correct_record(self, actor: Student, record_id: int, new_status: AttendanceStatus,
                       reason: str, source: ChangeSource) -> None:
        """Одиночная правка (в т.ч. из спора, source = DISPUTE - без проверки окна правки)."""
        raise NotImplementedError("ЛР4")

    def get_unmarked_lessons(self, user: Student) -> list[Lesson]:
        """Начавшиеся занятия группы, у которых есть записи NOT_MARKED (или нет записей)."""
        raise NotImplementedError("ЛР4")
