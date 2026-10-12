from attendance.models import Teacher

from .policy import AccessPolicy


class CourseService:
    def __init__(self, policy: AccessPolicy):
        self.policy = policy

    def set_threshold(self, teacher: Teacher, course_id: int, percent: int) -> None:
        """policy.can_set_threshold, иначе AccessDeniedError;
        course.set_threshold(percent) проверяет 0..100; UPDATE Course."""
        raise NotImplementedError("ЛР4")
