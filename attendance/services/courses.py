from attendance.errors import AccessDeniedError
from attendance.models import Course, Teacher

from .policy import AccessPolicy


class CourseService:
    def __init__(self, policy: AccessPolicy):
        self.policy = policy

    def set_threshold(self, teacher: Teacher, course_id: int, percent: int) -> None:
        """policy.can_set_threshold, иначе AccessDeniedError;
        course.set_threshold(percent) проверяет 0..100; UPDATE Course."""
        course = Course.objects.get(pk=course_id)
        if not self.policy.can_set_threshold(teacher, course):
            raise AccessDeniedError("Вы можете менять порог только своих курсов")
        course.set_threshold(percent)

    def for_teacher(self, teacher: Teacher) -> list[Course]:
        return list(teacher.courses.select_related("group", "subject").order_by("subject__name"))
