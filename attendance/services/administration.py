from django.db import transaction
from django.db.models import Q

from attendance.errors import AccessDeniedError
from attendance.models import AttendanceChange, Delegation, Dispute, Group, Student, Teacher, User


class AdministrationService:
    @staticmethod
    def _require_admin(actor):
        if not actor.is_active or not actor.is_staff:
            raise AccessDeniedError("Нужны права администратора")

    @transaction.atomic
    def delete_group(self, actor: User, group: Group) -> None:
        self._require_admin(actor)
        user_ids = list(group.students.values_list("user_id", flat=True))
        # Сначала удаляется история вместе с занятиями, затем ее участники.
        group.courses.all().delete()
        Delegation.objects.filter(Q(delegate__group=group) | Q(granted_by__group=group)).delete()
        group.students.all().delete()
        group.delete()
        User.objects.filter(pk__in=user_ids, is_staff=False, is_superuser=False, teacher__isnull=True).delete()

    @transaction.atomic
    def delete_teacher(self, actor: User, teacher: Teacher) -> None:
        self._require_admin(actor)
        user = teacher.user
        teacher.delete()
        if not user.is_staff and not user.is_superuser and not Student.objects.filter(user=user).exists():
            if AttendanceChange.objects.filter(changed_by=user).exists() or Dispute.objects.filter(resolved_by=user).exists():
                user.is_active = False
                user.save(update_fields=["is_active"])
            else:
                user.delete()
