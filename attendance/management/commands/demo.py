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
            print("\nГотово. Демонстрационные данные удалены.")

        # Чтобы окно консоли не закрывалось сразу после вывода
        if not options["no_wait"] and sys.stdin.isatty():
            try:
                input("Нажмите Enter для выхода...")
            except EOFError:
                pass

    # Подготовка данных

    def setup(self):
        self.tz = timezone.get_current_timezone()
        # Фиксированное «сейчас», чтобы вывод не зависел от даты запуска
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

        def teacher(login, name):
            return Teacher.objects.create(user=User.objects.create(username=login, last_name=name))

        self.teacher = teacher("teacher", "Преподаватель А.")
        # stranger не ведёт курс - для проверки прав преподавателя
        self.stranger = teacher("stranger", "Чужой")

        subject = Subject.objects.create(name="Программная инженерия")
        self.course = Course.objects.create(group=group, subject=subject, semester="2026-осень")
        self.course.teachers.add(self.teacher)

        # 10 занятий: раз в неделю по вторникам, лекции и лабораторные чередуются
        first_lesson = datetime(2026, 9, 1, 10, 0, tzinfo=self.tz)
        self.lessons = []
        for n in range(10):
            start = first_lesson + timedelta(weeks=n)
            lesson = Lesson.objects.create(
                course=self.course,
                teacher=self.teacher,
                start_at=start,
                end_at=start + timedelta(minutes=90),
                type=LessonType.LECTURE if n % 2 == 0 else LessonType.LAB,
            )
            self.lessons.append(lesson)

        self.today = self.lessons[4]  # 29 сентября - «сегодня»

        # Записи NOT_MARKED для всех студентов на все занятия
        self.records = {}
        for lesson in self.lessons:
            for s in self.students:
                record = AttendanceRecord.objects.create(lesson=lesson, student=s)
                self.records[(lesson.pk, s.pk)] = record

    def rec(self, lesson, student) -> AttendanceRecord:
        return self.records[(lesson.pk, student.pk)]

    def mark(self, lesson, student, status):
        self.rec(lesson, student).change(status, self.ivanov, "", lesson.start_at)

    def show_stats(self, title):
        print(f"  {title}")
        for s in self.students:
            own = [r for r in self.records.values() if r.student_id == s.pk]
            st = AttendanceCalculator.calculate(self.lessons, own,
                                                self.course.threshold_percent, self.now)
            icon = AttendanceCalculator.get_icon(st.level)

            print(f"    {s.user.full_name:<20} "
                  f"пропусков {st.missed}, "
                  f"допустимо ещё {st.allowed_misses:>2}, "
                  f"процент {st.percent:>3}%, "
                  f"не отмечено {st.not_marked}  {icon}")

    # Сценарий

    def run(self):
        self.setup()

        self.step_login()
        self.step_who_can_mark()
        self.step_marking()
        self.step_edit_with_reason()
        self.step_edit_window()
        self.step_threshold()
        self.step_dispute()
        self.step_teacher_threshold()
        self.step_delegation()

    def step_login(self):
        print("0. Вход в систему")

        correct = self.ivanov.user.check_password("secret")
        wrong = self.ivanov.user.check_password("qwerty")
        print(f"  Иванов, верный пароль: {yes(correct)}; неверный: {yes(wrong)}")

    def step_who_can_mark(self):
        print("\n1. Кто может отмечать занятие сегодня (12:00)")

        for s in (self.ivanov, self.petrova, self.sidorov):
            can = self.policy.can_mark(s, self.today, self.now)
            print(f"  {s.user.full_name:<20} может отмечать: {yes(can)}")

    def step_marking(self):
        print("\n2. Предыдущие занятия (для статистики) и отметка сегодняшнего")

        # Кузнецов пропустил 1-е, 2-е и 4-е занятия
        missed_by_kuznetsov = (self.lessons[0], self.lessons[1], self.lessons[3])
        for lesson in self.lessons[:4]:
            for s in self.students:
                absent = s is self.kuznetsov and lesson in missed_by_kuznetsov
                self.mark(lesson, s, A if absent else P)

        today_marks = [(self.ivanov, P), (self.petrova, P), (self.sidorov, A), (self.kuznetsov, A)]
        for s, status in today_marks:
            self.mark(self.today, s, status)
            print(f"  {s.user.full_name:<20} -> {status.value}")

        self.show_stats("Статистика после отметки:")

    def step_edit_with_reason(self):
        print("\n3. Правка отметки: нужна причина")

        # Первая отметка уже есть, поэтому любая правка - только с причиной
        self.petrova_record = rec = self.rec(self.today, self.petrova)
        try:
            rec.change(A, self.ivanov, "", self.now)
        except ReasonRequiredError as e:
            print(f"  без причины: ошибка - {e}")

        rec.change(A, self.ivanov, "Ошибся, Петрова ушла с пары", self.now)
        rec.change(P, self.ivanov, "Вернулась, была в аудитории", self.now)

        print("  История изменений отметки Петровой (из БД):")
        for c in rec.changes.all():
            print(f"    {c.old_status:>10} -> {c.new_status:<10} [{c.source}] "
                  f"кто: {c.changed_by.user.full_name}, причина: {c.reason or '-'}")

    def step_edit_window(self):
        print("\n4. Граница окна редактирования (до 00:00 следующего дня)")

        before_midnight = datetime(2026, 9, 29, 23, 59, 59, tzinfo=self.tz)
        midnight = datetime(2026, 9, 30, 0, 0, 0, tzinfo=self.tz)
        for moment in (before_midnight, midnight):
            can = self.policy.can_edit(self.ivanov, self.petrova_record, moment)
            print(f"  {moment:%Y-%m-%d %H:%M:%S}: староста может править отметку: {yes(can)}")

    def step_threshold(self):
        print("\n5. Порог посещаемости и иконки")
        print("  Порог 50%, всего 10 занятий:")

        for missed in range(0, 8):
            allowed = AttendanceCalculator.allowed_misses(10, missed, 50)
            level = AttendanceCalculator.get_level(allowed)
            icon = AttendanceCalculator.get_icon(level)
            print(f"    пропусков {missed}: допустимо ещё {allowed:>2}  {level.value:<16} {icon}")

    def step_dispute(self):
        print("\n6. Спор: Кузнецов оспаривает пропуск 29.09")

        disputed = self.rec(self.today, self.kuznetsov)
        dispute = Dispute.objects.create(record=disputed, comment="Я был, староста ошибся",
                                         created_at=self.now)

        # Сидоров - рядовой студент, споры рассматривает только староста или зам.
        sidorov_can = self.policy.can_resolve_dispute(self.sidorov, dispute)
        ivanov_can = self.policy.can_resolve_dispute(self.ivanov, dispute)
        print(f"  Сидоров может рассматривать спор: {yes(sidorov_can)}")
        print(f"  Иванов  может рассматривать спор: {yes(ivanov_can)}")

        # Решение по спору и исправление отметки - два отдельных шага
        dispute.resolve(fix=True, by=self.ivanov, comment="", now=self.now)
        last = disputed.change(P, self.ivanov, f"Спор №{dispute.pk}: исправлено", self.now,
                               source=ChangeSource.DISPUTE)
        print(f"  Спор: {dispute.status}; отметка теперь {disputed.status}; "
              f"источник правки: {last.source}")

        self.show_stats("Статистика после решения спора:")

        # Отклонить спор без комментария нельзя
        try:
            Dispute(record=disputed).resolve(False, self.ivanov, "", self.now)
        except ReasonRequiredError as e:
            print(f"  Отказ без комментария: ошибка - {e}")

    def step_teacher_threshold(self):
        print("\n7. Порог меняет преподаватель")

        own = self.policy.can_set_threshold(self.teacher, self.course)
        stranger = self.policy.can_set_threshold(self.stranger, self.course)
        print(f"  Свой преподаватель может: {yes(own)}; чужой: {yes(stranger)}")

        self.course.set_threshold(70)
        self.show_stats("Порог 70%:")

        try:
            self.course.set_threshold(150)
        except ValueError as e:
            print(f"  Порог 150: ошибка - {e}")

    def step_delegation(self):
        print("\n8. Временная замена старосты (06.10)")

        self.now = datetime(2026, 10, 6, 9, 0, tzinfo=self.tz)
        lesson = self.lessons[5]
        ivanov, sidorov, kuznetsov = self.ivanov, self.sidorov, self.kuznetsov

        can = self.policy.can_mark(sidorov, lesson, self.now)
        print(f"  До назначения Сидоров может отмечать: {yes(can)}")
        can = self.policy.can_assign_delegate(ivanov, sidorov, self.now)
        print(f"  Староста может назначить Сидорова: {yes(can)}")

        # Замена действует до 00:00 следующего дня
        deleg = Delegation.objects.create(granted_by=ivanov, delegate=sidorov,
                                          granted_at=self.now,
                                          valid_until=next_midnight(self.now))

        can = self.policy.can_mark(sidorov, lesson, self.now)
        print(f"  После назначения Сидоров может отмечать: {yes(can)}")

        # У делегата роль MEMBER, поэтому передать права дальше он не может
        can = self.policy.can_assign_delegate(sidorov, kuznetsov, self.now)
        print(f"  Сидоров может назначить Кузнецова: {yes(can)}")

        before_midnight = datetime(2026, 10, 6, 23, 59, 59, tzinfo=self.tz)
        print(f"  Замена в 23:59:59: {yes(deleg.is_active(before_midnight))}, "
              f"в 00:00:00: {yes(deleg.is_active(deleg.valid_until))}")

        try:
            deleg.revoke(kuznetsov, self.now)
        except AccessDeniedError as e:
            print(f"  Кузнецов пытается отозвать замену: ошибка - {e}")

        deleg.revoke(ivanov, self.now)
        can = self.policy.can_mark(sidorov, lesson, self.now)
        print(f"  После досрочного отзыва Сидоров может отмечать: {yes(can)}")
