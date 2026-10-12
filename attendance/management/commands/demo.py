"""ЛР2: классы предметной области в действии (аналог Program.Main из методички).

Показывает на моделях из UML/class_domain.puml: права на отметку, правку с причиной,
окно редактирования, расчёт порога и иконок, спор и временную замену старосты.
Данные создаются в транзакции, которая в конце откатывается - БД остаётся чистой.

Запуск:  python manage.py demo
"""
import sys
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from attendance.errors import AccessDeniedError, ReasonRequiredError
from attendance.models import (AttendanceRecord, AttendanceStatus, ChangeSource, Course,
                               Delegation, Dispute, Group, GroupRole, Lesson, LessonType,
                               Student, Subject, Teacher, User)
from attendance.services import AccessPolicy, AttendanceCalculator
from attendance.timeutils import next_midnight

P, A = AttendanceStatus.PRESENT, AttendanceStatus.ABSENT


class _Rollback(Exception):
    pass


def yes(flag: bool) -> str:
    return "да" if flag else "нет"


class Command(BaseCommand):
    help = "Демонстрация правил предметной области (ЛР2); изменения в БД откатываются"

    def add_arguments(self, parser):
        parser.add_argument("--no-wait", action="store_true",
                            help="не ждать нажатия Enter в конце (для скриптов и тестов)")

    def handle(self, *args, **options):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        try:
            with transaction.atomic():
                self.run()
                raise _Rollback
        except _Rollback:
            print("\nГотово. Демонстрационные данные удалены (транзакция откачена).")
        # Чтобы окно консоли не закрывалось сразу после вывода
        if not options["no_wait"] and sys.stdin.isatty():
            try:
                input("Нажмите Enter для выхода...")
            except EOFError:
                pass

    # ------------------------------------------------------------------ данные
    def setup(self):
        self.tz = timezone.get_current_timezone()
        self.now = datetime(2026, 9, 29, 12, 0, tzinfo=self.tz)
        self.policy = AccessPolicy()

        group = Group.objects.create(name="ИВТ-31")

        def student(login, name, role=GroupRole.MEMBER):
            user = User.objects.create(username=login, last_name=name)
            return Student.objects.create(user=user, group=group, role=role)

        self.ivanov = student("ivanov", "Иванов (староста)", GroupRole.HEADMAN)
        self.ivanov.user.set_password("secret")
        self.ivanov.user.save()
        self.petrova = student("petrova", "Петрова (зам.)", GroupRole.DEPUTY)
        self.sidorov = student("sidorov", "Сидоров")
        self.kuznetsov = student("kuznetsov", "Кузнецов")
        self.students = [self.ivanov, self.petrova, self.sidorov, self.kuznetsov]

        self.teacher = Teacher.objects.create(user=User.objects.create(username="teacher", last_name="Преподаватель А."))
        self.stranger = Teacher.objects.create(user=User.objects.create(username="stranger", last_name="Чужой"))
        self.course = Course.objects.create(group=group, semester="2026-осень",
                                            subject=Subject.objects.create(name="Программная инженерия"))
        self.course.teachers.add(self.teacher)

        # 10 занятий: раз в неделю по вторникам, лекции и лабораторные чередуются
        self.lessons = []
        for n in range(10):
            start = datetime(2026, 9, 1, 10, 0, tzinfo=self.tz) + timedelta(weeks=n)
            self.lessons.append(Lesson.objects.create(
                course=self.course, teacher=self.teacher, start_at=start,
                end_at=start + timedelta(minutes=90),
                type=LessonType.LECTURE if n % 2 == 0 else LessonType.LAB))
        self.today = self.lessons[4]           # 29 сентября - «сегодня»

        self.records = {(l.pk, s.pk): AttendanceRecord.objects.create(lesson=l, student=s)
                        for l in self.lessons for s in self.students}

    def rec(self, lesson, student) -> AttendanceRecord:
        return self.records[(lesson.pk, student.pk)]

    def mark(self, lesson, student, status):
        self.rec(lesson, student).change(status, self.ivanov, "", lesson.start_at)

    def show_stats(self, title):
        print(f"  {title}")
        for s in self.students:
            own = [r for r in self.records.values() if r.student_id == s.pk]
            st = AttendanceCalculator.calculate(self.lessons, own, self.course.threshold_percent, self.now)
            icon = AttendanceCalculator.get_icon(st.level)
            print(f"    {s.user.full_name:<20} пропусков {st.missed}, допустимо ещё {st.allowed_misses:>2}, "
                  f"процент {st.percent:>3}%, не отмечено {st.not_marked}  {icon}")

    # ------------------------------------------------------------------ сценарий
    def run(self):
        self.setup()
        policy, ivanov, petrova, sidorov, kuznetsov = (
            self.policy, self.ivanov, self.petrova, self.sidorov, self.kuznetsov)

        print("=== 0. Вход в систему ===")
        print(f"  Иванов, верный пароль: {yes(ivanov.user.check_password('secret'))}; "
              f"неверный: {yes(ivanov.user.check_password('qwerty'))}")

        print("\n=== 1. Кто может отмечать занятие сегодня (12:00) ===")
        for s in (ivanov, petrova, sidorov):
            print(f"  {s.user.full_name:<20} может отмечать: {yes(policy.can_mark(s, self.today, self.now))}")

        print("\n=== 2. Предыдущие занятия (для статистики) и отметка сегодняшнего ===")
        for lesson in self.lessons[:4]:
            for s in self.students:
                absent = s is kuznetsov and lesson in (self.lessons[0], self.lessons[1], self.lessons[3])
                self.mark(lesson, s, A if absent else P)
        for s, st in ((ivanov, P), (petrova, P), (sidorov, A), (kuznetsov, A)):
            self.mark(self.today, s, st)
            print(f"  {s.user.full_name:<20} -> {st.value}")
        self.show_stats("Статистика после отметки:")

        print("\n=== 3. Правка отметки: нужна причина ===")
        rec = self.rec(self.today, petrova)
        try:
            rec.change(A, ivanov, "", self.now)
        except ReasonRequiredError as e:
            print(f"  без причины: ошибка - {e}")
        rec.change(A, ivanov, "Ошибся, Петрова ушла с пары", self.now)
        rec.change(P, ivanov, "Вернулась, была в аудитории", self.now)
        print("  История изменений отметки Петровой (из БД):")
        for c in rec.changes.all():
            print(f"    {c.old_status:>10} -> {c.new_status:<10} [{c.source}] "
                  f"кто: {c.changed_by.user.full_name}, причина: {c.reason or '-'}")

        print("\n=== 4. Граница окна редактирования (до 00:00 следующего дня) ===")
        for moment in (datetime(2026, 9, 29, 23, 59, 59, tzinfo=self.tz),
                       datetime(2026, 9, 30, 0, 0, 0, tzinfo=self.tz)):
            print(f"  {moment:%Y-%m-%d %H:%M:%S}: староста может править отметку: "
                  f"{yes(policy.can_edit(ivanov, rec, moment))}")

        print("\n=== 5. Порог посещаемости и иконки ===")
        print("  Порог 50%, всего 10 занятий:")
        for missed in range(0, 8):
            allowed = AttendanceCalculator.allowed_misses(10, missed, 50)
            level = AttendanceCalculator.get_level(allowed)
            print(f"    пропусков {missed}: допустимо ещё {allowed:>2}  {level.value:<16} "
                  f"{AttendanceCalculator.get_icon(level)}")

        print("\n=== 6. Спор: Кузнецов оспаривает пропуск 29.09 ===")
        disputed = self.rec(self.today, kuznetsov)
        dispute = Dispute.objects.create(record=disputed, comment="Я был, староста ошибся", created_at=self.now)
        print(f"  Сидоров может рассматривать спор: {yes(policy.can_resolve_dispute(sidorov, dispute))}")
        print(f"  Иванов  может рассматривать спор: {yes(policy.can_resolve_dispute(ivanov, dispute))}")
        dispute.resolve(fix=True, by=ivanov, comment="", now=self.now)
        last = disputed.change(P, ivanov, f"Спор №{dispute.pk}: исправлено", self.now, source=ChangeSource.DISPUTE)
        print(f"  Спор: {dispute.status}; отметка теперь {disputed.status}; источник правки: {last.source}")
        self.show_stats("Статистика после решения спора:")
        try:
            Dispute(record=disputed).resolve(False, ivanov, "", self.now)
        except ReasonRequiredError as e:
            print(f"  Отказ без комментария: ошибка - {e}")

        print("\n=== 7. Порог меняет преподаватель ===")
        print(f"  Свой преподаватель может: {yes(policy.can_set_threshold(self.teacher, self.course))}; "
              f"чужой: {yes(policy.can_set_threshold(self.stranger, self.course))}")
        self.course.set_threshold(70)
        self.show_stats("Порог 70%:")
        try:
            self.course.set_threshold(150)
        except ValueError as e:
            print(f"  Порог 150: ошибка - {e}")

        print("\n=== 8. Временная замена старосты (06.10) ===")
        self.now = datetime(2026, 10, 6, 9, 0, tzinfo=self.tz)
        next_lesson = self.lessons[5]
        print(f"  До назначения Сидоров может отмечать: {yes(policy.can_mark(sidorov, next_lesson, self.now))}")
        print(f"  Староста может назначить Сидорова: {yes(policy.can_assign_delegate(ivanov, sidorov, self.now))}")
        deleg = Delegation.objects.create(granted_by=ivanov, delegate=sidorov,
                                          granted_at=self.now, valid_until=next_midnight(self.now))
        print(f"  После назначения Сидоров может отмечать: {yes(policy.can_mark(sidorov, next_lesson, self.now))}")
        print(f"  Сидоров может назначить Кузнецова: {yes(policy.can_assign_delegate(sidorov, kuznetsov, self.now))}")
        print(f"  Замена в 23:59:59: {yes(deleg.is_active(datetime(2026, 10, 6, 23, 59, 59, tzinfo=self.tz)))}, "
              f"в 00:00:00: {yes(deleg.is_active(deleg.valid_until))}")
        try:
            deleg.revoke(kuznetsov, self.now)
        except AccessDeniedError as e:
            print(f"  Кузнецов пытается отозвать замену: ошибка - {e}")
        deleg.revoke(ivanov, self.now)
        print(f"  После досрочного отзыва Сидоров может отмечать: {yes(policy.can_mark(sidorov, next_lesson, self.now))}")
