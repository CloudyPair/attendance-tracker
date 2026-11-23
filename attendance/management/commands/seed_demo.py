"""Одна группа и 16 учётных записей; занятия только из реального календаря."""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceStatus, Group, GroupRole, Lesson, Student, Teacher, User
from attendance.services import build_services
from attendance.services.schedule_import import ScheduleImporter
from attendance.timeutils import day_start


STUDENTS = [
    ("Иванов", "Александр Сергеевич"), ("Петрова", "Мария Андреевна"),
    ("Сидоров", "Дмитрий Олегович"), ("Кузнецова", "Анна Игоревна"),
    ("Смирнов", "Михаил Павлович"), ("Волкова", "Екатерина Романовна"),
    ("Соколов", "Артём Денисович"), ("Лебедева", "Софья Максимовна"),
    ("Козлов", "Никита Алексеевич"), ("Новикова", "Дарья Евгеньевна"),
    ("Морозов", "Илья Викторович"), ("Орлова", "Полина Дмитриевна"),
    ("Попов", "Кирилл Андреевич"), ("Зайцева", "Алиса Николаевна"),
    ("Фёдоров", "Егор Михайлович"),
]


class SeedClock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


class Command(BaseCommand):
    help = "Создать ИВТ-31: 15 вымышленных студентов, одного преподавателя и реальное расписание"

    def add_arguments(self, parser):
        parser.add_argument("--ics", type=Path, default=settings.BASE_DIR / "data" / "ivt31.ics")
        parser.add_argument("--password", default="1234")
        parser.add_argument("--no-marks", action="store_true", help="Не добавлять отметки двух прошедших занятий")

    @transaction.atomic
    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(name="ИВТ-31")
        usernames = [f"ivt31_{index:02d}" for index in range(1, 16)]
        if group.students.exclude(user__username__in=usernames).exists():
            raise CommandError("В ИВТ-31 уже есть другие студенты. Демонстрационные данные не добавлены")
        students = []
        for index, (last_name, first_name) in enumerate(STUDENTS, 1):
            user, created = User.objects.get_or_create(username=f"ivt31_{index:02d}",
                                                      defaults={"last_name": last_name, "first_name": first_name})
            if created:
                user.set_password(options["password"])
                user.save()
            elif not Student.objects.filter(user=user, group=group).exists():
                raise CommandError(f"Учётная запись {user.username} уже используется")
            role = GroupRole.HEADMAN if index == 1 else GroupRole.DEPUTY if index == 2 else GroupRole.MEMBER
            student, _ = Student.objects.get_or_create(user=user, defaults={"group": group, "role": role})
            students.append(student)

        teacher_user, created = User.objects.get_or_create(username="ivt31_teacher",
            defaults={"last_name": "Балабаев", "first_name": "Сергей Андреевич"})
        if created:
            teacher_user.set_password(options["password"])
            teacher_user.save()
        elif not Teacher.objects.filter(user=teacher_user).exists():
            raise CommandError("Учётная запись ivt31_teacher уже используется")
        teacher, _ = Teacher.objects.get_or_create(user=teacher_user)

        if not Lesson.objects.filter(course__group=group).exists():
            try:
                source = json.loads((settings.BASE_DIR / "data" / "ivt31_source.json").read_text(encoding="utf-8"))
                semester = source["semester"].replace("Осенний семестр", "Осень").replace("Весенний семестр", "Весна")
                with options["ics"].open("rb") as calendar:
                    result = ScheduleImporter().import_ics(calendar, group.pk, semester=semester)
            except (OSError, ValueError, KeyError) as error:
                raise CommandError(str(error)) from error
            if result.errors:
                raise CommandError("; ".join(result.errors))
            self.stdout.write(f"Импортировано занятий: {result.created}; служебных событий пропущено: {result.skipped}")

        # В демонстрации один преподаватель рассматривает заявки всех предметов группы.
        # Реальные ФИО из ICS остаются в Lesson.teacher_name.
        for course in group.courses.all():
            course.teachers.add(teacher)
        if not options["no_marks"]:
            lessons = list(Lesson.objects.filter(course__group=group,
                            start_at__lt=day_start(timezone.now())).order_by("-start_at", "-pk")[:2])
            for index, lesson in enumerate(reversed(lessons)):
                if lesson.records.exists():
                    continue
                services = build_services(clock=SeedClock(lesson.start_at))
                marks = {student.pk: AttendanceStatus.ABSENT if student.pk == students[index + 2].pk
                         else AttendanceStatus.PRESENT for student in students}
                services.attendance.save_marks(students[0], lesson.pk, marks, expected_version=lesson.marking_version)
        self.stdout.write(self.style.SUCCESS("ИВТ-31 готова: 15 студентов, один преподаватель. Существующие данные сохранены."))
        self.stdout.write("Староста: ivt31_01; заместитель: ivt31_02; студент: ivt31_03; преподаватель: ivt31_teacher")
        self.stdout.write("Пароль новых учётных записей: значение --password (по умолчанию 1234)")
