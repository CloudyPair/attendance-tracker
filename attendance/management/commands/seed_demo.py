"""Демо-пользователи для проверки входа на сайт (итерация 1, ЛР4).

Создаёт группу ПИН-21 со старостой, заместителем и студентом и преподавателя.
В отличие от `manage.py demo` (ЛР2), данные остаются в БД.

Запуск:  python manage.py seed_demo
Вход:    starosta, zam (заместитель), student1, prepod (преподаватель);
         пароль у всех - demo12345
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from attendance.models import Group, GroupRole, Student, Teacher, User

GROUP_NAME = "ПИН-21"  # не ИВТ-31: та группа нужна `manage.py demo`
PASSWORD = "demo12345"


class Command(BaseCommand):
    help = "Создать демо-пользователей для проверки входа (группа ПИН-21)"

    def handle(self, *args, **options):
        if Group.objects.filter(name=GROUP_NAME).exists():
            raise CommandError(f"Группа {GROUP_NAME} уже есть - демо-данные загружены раньше")
        with transaction.atomic():
            self.create()
        self.stdout.write(self.style.SUCCESS(
            f"Готово. Вход: starosta, zam (заместитель), student1, prepod (преподаватель); "
            f"пароль {PASSWORD}"))

    def create(self):
        def user(login, last, first):
            u = User(username=login, last_name=last, first_name=first)
            u.set_password(PASSWORD)
            u.save()
            return u

        group = Group.objects.create(name=GROUP_NAME)
        for login, last, first, role in [
            ("starosta", "Васильева", "Мария", GroupRole.HEADMAN),
            ("zam", "Борисов", "Иван", GroupRole.DEPUTY),
            ("student1", "Григорьев", "Олег", GroupRole.MEMBER),
        ]:
            Student.objects.create(user=user(login, last, first), group=group, role=role)
        Teacher.objects.create(user=user("prepod", "Орлов", "Сергей"))
