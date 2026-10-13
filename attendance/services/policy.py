"""Права доступа: кто что может делать.

Время передаётся параметром `now`, поэтому правила легко проверить на любой момент.
"""
from datetime import datetime

from attendance.models import (AttendanceRecord, AttendanceStatus, Course, Dispute, GroupRole,
                               Lesson, Student, Teacher)


class AccessPolicy:
    def can_mark(self, user: Student, lesson: Lesson, now: datetime) -> bool:
        """Отмечать может староста, заместитель или замена - только свою группу
        и только в день занятия."""
        if not user.belongs_to(lesson.course.group):
            return False

        has_role = user.is_headman_or_deputy() or user.has_active_delegation(now)
        return has_role and lesson.is_marking_window_open(now)

    def can_edit(self, user: Student, record: AttendanceRecord, now: datetime) -> bool:
        """Править можно только уже сохранённую отметку, по тем же правилам, что и отмечать."""
        if record.status == AttendanceStatus.NOT_MARKED:
            return False
        return self.can_mark(user, record.lesson, now)

    def can_assign_delegate(self, grantor: Student, delegate: Student, now: datetime) -> bool:
        """Назначить замену может староста или зам. своей группы,
        заменой - только рядовой студент без действующей замены."""
        # У делегата роль MEMBER, поэтому передать права дальше он не может
        return (grantor.is_headman_or_deputy()
                and grantor.belongs_to(delegate.group)
                and delegate.role == GroupRole.MEMBER
                and not delegate.has_active_delegation(now))

    def can_resolve_dispute(self, user: Student, dispute: Dispute) -> bool:
        """Спор рассматривает староста или зам. той же группы, но не по своей отметке."""
        disputant = dispute.record.student
        return (user.is_headman_or_deputy()
                and user.pk != disputant.pk
                and user.belongs_to(disputant.group))

    def can_view_course(self, teacher: Teacher, course: Course) -> bool:
        return course.teachers.filter(pk=teacher.pk).exists()

    def can_set_threshold(self, teacher: Teacher, course: Course) -> bool:
        # Порог задаёт любой преподаватель курса
        return self.can_view_course(teacher, course)
