"""Второй клиент общего ядра. ORM выполняется в синхронном потоке Django."""
import asyncio
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import close_old_connections, OperationalError
from django.utils import timezone

from attendance.errors import DomainError
from attendance.services import build_services
from attendance.timeutils import day_start


class InputState(StatesGroup):
    text = State()


def ui(text):
    return str(text).translate(str.maketrans({"ё": "е", "Ё": "Е", "·": None}))


def button(text, data):
    return InlineKeyboardButton(text=ui(text)[:60], callback_data=data)


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_rows():
    return [[button("Сегодня", "today"), button("Неделя", "week")],
            [button("Посещаемость", "stats"), button("Пропуски", "absences:1")],
            [button("Мои споры", "disputes:1"), button("Замена старосты", "delegation")],
            [button("Уведомления", "notifications")],
            [button("Выйти из аккаунта", "logout")]]


def pagination(rows, page, prefix):
    controls = []
    if page.has_previous():
        controls.append(button("← Назад", f"{prefix}:{page.previous_page_number()}"))
    if page.has_next():
        controls.append(button("Далее →", f"{prefix}:{page.next_page_number()}"))
    if controls:
        rows.append(controls)
    rows.append([button("Меню", "menu")])


def screen(chat_id, action="menu", number=1):
    """Сервисные чтения материализуются здесь, до возврата в async-обработчик."""
    services = build_services()
    student = services.telegram_link.student_for_chat(str(chat_id))
    if action == "menu":
        return ui(f"ФЛАГ / {student.group.name}\n{student.user.full_name}\nВыберите раздел."), keyboard(home_rows())
    rows = []
    lines = []
    if action in ("today", "week"):
        start = day_start(timezone.now())
        if action == "week":
            start -= timedelta(days=start.weekday())
        end = start + timedelta(days=7 if action == "week" else 1)
        lessons = services.attendance.lessons_for_student(student, start, end)
        lines = ["Расписание на сегодня" if action == "today" else "Расписание на неделю"]
        previous_day = None
        for row in lessons:
            lesson = row.lesson
            local = timezone.localtime(lesson.start_at)
            if local.date() != previous_day:
                lines.append(f"\n{local:%d.%m.%Y}")
                previous_day = local.date()
            mark = {"PRESENT": "✅ Был", "ABSENT": "❌ Не был"}.get(row.status, "⚪ Не отмечено")
            lines.append(f"\n{local:%H:%M}–{timezone.localtime(lesson.end_at):%H:%M} "
                f"{lesson.course.subject.name}\n{lesson.get_type_display()}, ауд. {lesson.room or '—'}\n"
                f"{lesson.teacher_name or 'Преподаватель не указан'}\n{mark}")
        if not lessons:
            lines.append("Занятий нет.")
        lines.append(f"\nОтметка группы на сайте: {settings.SITE_URL}/")
    elif action == "stats":
        start, end = services.statistics.period_for_student(student)
        lines = ["Посещаемость за семестр"]
        for report in services.statistics.for_student(student, start, end):
            stats = report.total
            percent = f"{stats.percent}%" if stats.marked else "Нет отметок"
            lines.append(f"\n{report.course.subject.name}: {percent}\n"
                f"Был: {stats.present}, не был: {stats.missed}, без отметки: {stats.not_marked}")
        if len(lines) == 1:
            lines.append("Расписание пока не загружено.")
    elif action == "absences":
        page = Paginator(services.disputes.absences(student), 4).get_page(number)
        lines = [f"Пропуски / сначала недавние\nСтраница {page.number} из {page.paginator.num_pages}"]
        for index, record in enumerate(page, 1):
            lines.append(f"\n{index}. {record.lesson.course.subject.name}\n"
                f"{timezone.localtime(record.lesson.start_at):%d.%m %H:%M} / ❌ Не был")
            pending = next((d for d in record.disputes.all() if d.status == "OPEN"), None)
            if pending:
                lines.append(f"Заявка №{pending.pk} на рассмотрении у преподавателя")
            else:
                rows.append([button(f"{index}. Оспорить", f"dispute:{record.pk}")])
        if not page.object_list:
            lines.append("Пропусков нет.")
        pagination(rows, page, "absences")
    elif action == "disputes":
        page = Paginator(services.disputes.list_for(student), 4).get_page(number)
        lines = [f"Мои споры / страница {page.number} из {page.paginator.num_pages}"]
        for dispute in page:
            lines.append(f"\n№{dispute.pk} / {dispute.get_status_display()}\n"
                f"{dispute.record.student.user.full_name}\n{dispute.record.lesson.course.subject.name}\n"
                f"{timezone.localtime(dispute.record.lesson.start_at):%d.%m %H:%M}\n{dispute.comment[:300]}")
            if dispute.resolution_comment:
                lines.append(f"Решение: {dispute.resolution_comment[:300]}")
            if dispute.attachment:
                lines.append("Документ приложен")
        if not page.object_list:
            lines.append("Споров пока нет.")
        pagination(rows, page, "disputes")
    elif action == "delegation":
        lines = ["Временная замена старосты до 00:00"]
        active = services.delegation.active_for(student)
        for delegation in active:
            lines.append(f"\n{delegation.delegate.user.full_name} / "
                         f"до {timezone.localtime(delegation.valid_until):%d.%m %H:%M}")
            if student.is_headman_or_deputy():
                rows.append([button(f"Отозвать: {delegation.delegate.user.full_name}", f"revoke:{delegation.pk}")])
        if not active:
            lines.append("Действующих замен нет.")
        if student.is_headman_or_deputy():
            lines.append("\nНазначить студента:")
            active_ids = {d.delegate_id for d in active}
            for candidate in services.delegation.candidates(student):
                if candidate.pk not in active_ids:
                    rows.append([button(candidate.user.full_name, f"assign:{candidate.pk}")])
    elif action == "notifications":
        link = services.telegram_link.get_link(student)
        lines = ["Уведомления включены." if link.notifications_enabled else "Уведомления выключены."]
        rows.append([button("Выключить" if link.notifications_enabled else "Включить",
                            "disable" if link.notifications_enabled else "enable")])
        lines.append("Выйти из аккаунта и отвязать Telegram: /logout")
    else:
        raise DomainError("Откройте меню заново")
    if action not in ("absences", "disputes"):
        rows.append([button("Меню", "menu")])
    return ui("\n".join(lines))[:4000], keyboard(rows)


def mutate(chat_id, action, object_id=0, text="", attachment=None):
    services = build_services()
    student = services.telegram_link.student_for_chat(str(chat_id))
    if action == "dispute":
        services.disputes.create(student, object_id, text, attachment)
        return "Заявка отправлена преподавателю предмета.", "disputes"
    if action in ("fix", "reject"):
        raise DomainError("Решение принимает преподаватель предмета на сайте")
    if action == "assign":
        services.delegation.assign_by_id(student, object_id)
        return "Замена назначена до 00:00.", "delegation"
    if action == "revoke":
        services.delegation.revoke(student, object_id)
        return "Замена отозвана.", "delegation"
    if action in ("enable", "disable"):
        services.telegram_link.set_notifications(student, action == "enable")
        return "Настройки сохранены.", "notifications"
    raise DomainError("Неизвестное действие")


def database_call(function, *args, **kwargs):
    close_old_connections()
    try:
        return function(*args, **kwargs)
    finally:
        close_old_connections()


async def db(function, *args, **kwargs):
    return await sync_to_async(database_call, thread_sensitive=True)(function, *args, **kwargs)


def make_router():
    router = Router()
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")

    async def show(message, action="menu", number=1, prefix=""):
        text, markup = await db(screen, message.chat.id, action, number)
        await message.answer(ui(prefix + text)[:4096], reply_markup=markup)

    async def logout(message, state):
        await state.clear()
        await db(lambda: build_services().telegram_link.unlink_chat(str(message.chat.id)))
        await message.answer("Вы вышли из аккаунта. Telegram отвязан, уведомления отключены.\n"
                             f"Для нового входа получите ссылку на сайте: {settings.SITE_URL}/telegram/")

    @router.message(CommandStart())
    async def start(message: Message, command: CommandObject, state: FSMContext):
        await state.clear()
        if command.args:
            await db(lambda: build_services().telegram_link.bind(command.args.strip(), str(message.chat.id)))
            await show(message, prefix="Telegram привязан.\n\n")
        else:
            await show(message)

    @router.message(Command("menu", "today", "week", "attendance", "absences", "disputes", "delegation", "cancel"))
    async def commands(message: Message, command: CommandObject, state: FSMContext):
        await state.clear()
        action = {"attendance": "stats", "cancel": "menu"}.get(command.command, command.command)
        await show(message, action)

    @router.message(Command("logout"))
    async def logout_command(message: Message, state: FSMContext):
        await logout(message, state)

    @router.callback_query()
    async def callbacks(query: CallbackQuery, state: FSMContext):
        await query.answer()
        action, _, raw_number = (query.data or "menu").partition(":")
        if action == "reason":
            action = "dispute"  # Совместимость со старыми кнопками до обновления бота.
        number = int(raw_number) if raw_number.isdigit() else 1
        await state.clear()
        if action == "logout":
            await logout(query.message, state)
        elif action == "dispute":
            # Проверяем привязку до начала диалога; само действие повторно проверяет права.
            await db(lambda: build_services().telegram_link.student_for_chat(str(query.message.chat.id)))
            await state.set_state(InputState.text)
            await state.update_data(action=action, object_id=number)
            await query.message.answer("Пришлите объяснение для преподавателя. Можно отправить справку "
                "как файл или фото до 5 МБ с объяснением в подписи.\nОтмена: /cancel")
        elif action in ("fix", "reject"):
            raise DomainError("Решение принимает преподаватель предмета на сайте")
        elif action in ("assign", "revoke", "enable", "disable"):
            prefix, target = await db(mutate, query.message.chat.id, action, number)
            await show(query.message, target, prefix=prefix + "\n\n")
        else:
            await show(query.message, action, number)

    @router.message(InputState.text)
    async def receive_text(message: Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        text = message.text or message.caption or ""
        if not text.strip() or len(text.strip()) > 2000:
            await message.answer("Введите от 1 до 2000 символов. Отмена: /cancel")
            return
        attachment = None
        upload = message.document or (message.photo[-1] if message.photo else None)
        if upload:
            if not upload.file_size or upload.file_size > 5 * 1024 * 1024:
                await message.answer("Размер вложения не должен превышать 5 МБ.")
                return
            # Привязка могла быть удалена во время диалога.
            await db(lambda: build_services().telegram_link.student_for_chat(str(message.chat.id)))
            buffer = await bot.download(upload)
            name = (message.document.file_name or "attachment") if message.document else "certificate.jpg"
            attachment = ContentFile(buffer.read(), name=Path(name).name)
        prefix, target = await db(mutate, message.chat.id, data["action"], data["object_id"], text, attachment)
        await state.clear()
        await show(message, target, prefix=prefix + "\n\n")

    @router.message()
    async def fallback(message: Message):
        await show(message)

    @router.errors()
    async def errors(event):
        error = event.exception
        if isinstance(error, DomainError):
            text = ui(str(error))
        elif isinstance(error, OperationalError):
            text = "Данные сейчас обновляются. Повторите действие через несколько секунд."
        else:
            # Не выводим текст исключения: сетевые ошибки могут содержать секретный URL.
            text = "Не удалось выполнить действие. Попробуйте еще раз или откройте /menu."
        update = event.update
        message = update.message or (update.callback_query.message if update.callback_query else None)
        if message is not None and message.chat.type == "private":
            if "Привяжите" in text:
                text += f"\n{settings.SITE_URL}/telegram/"
            with suppress(Exception):
                await message.answer(text[:4096])
        return True

    return router


def maintenance():
    services = build_services()
    services.delegation.notify_expired(services.delegation.clock.now())
    services.notifications.retry_pending()


async def worker():
    while True:
        try:
            await db(maintenance)
        except Exception:
            # Очередь остается в БД; следующая итерация повторит попытку.
            pass
        await asyncio.sleep(30)


async def run_bot(on_ready=None):
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(make_router())
    task = None
    try:
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError("Для polling сначала отключите webhook этого бота")
        await bot.set_my_commands([
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="week", description="Расписание на неделю"),
            BotCommand(command="attendance", description="Моя посещаемость"),
            BotCommand(command="absences", description="Пропуски и подача спора"),
            BotCommand(command="disputes", description="Мои споры"),
            BotCommand(command="delegation", description="Замена старосты"),
            BotCommand(command="logout", description="Выйти из аккаунта и отвязать Telegram"),
            BotCommand(command="cancel", description="Отменить ввод"),
        ])
        task = asyncio.create_task(worker())
        if on_ready:
            on_ready()
        await dispatcher.start_polling(bot, close_bot_session=False, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await bot.session.close()
