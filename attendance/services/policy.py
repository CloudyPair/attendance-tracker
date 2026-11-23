"""Правила доступа: кто что может. Время передаётся параметром - политика не зависит от часов."""
from datetime import datetime

from attendance.models import (AttendanceRecord, AttendanceStatus, Course, Dispute, GroupRole,
                               Lesson, Student, Teacher)


class AccessPolicy:
    def can_mark(self, user: Student, lesson: Lesson, now: datetime) -> bool:
        if not isinstance(user, Student) or not user.belongs_to(lesson.course.group):
            return False
        has_role = user.is_headman_or_deputy() or user.has_active_delegation(now)
        return has_role and lesson.is_marking_window_open(now)

    def can_edit(self, user: Student, record: AttendanceRecord, now: datetime) -> bool:
        return record.status != AttendanceStatus.NOT_MARKED and self.can_mark(user, record.lesson, now)

    def can_assign_delegate(self, grantor: Student, delegate: Student, now: datetime) -> bool:
        # Делегат имеет роль MEMBER, поэтому передать права дальше не может
        return (grantor.is_headman_or_deputy()
                and grantor.belongs_to(delegate.group)
                and delegate.role == GroupRole.MEMBER
                and not delegate.has_active_delegation(now))

    def can_resolve_dispute(self, user: Teacher, dispute: Dispute) -> bool:
        return (isinstance(user, Teacher)
                and user.user_id != dispute.record.student.user_id
                and self.can_view_course(user, dispute.record.lesson.course))

    def can_view_course(self, teacher: Teacher, course: Course) -> bool:
        return course.teachers.filter(pk=teacher.pk).exists()

    def can_set_threshold(self, teacher: Teacher, course: Course) -> bool:
        return course.teachers.filter(pk=teacher.pk).exists()
