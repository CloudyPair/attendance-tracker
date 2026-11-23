"""Приемка aiogram через настоящий Dispatcher и полностью автономный Bot API."""
import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, GetMe, SendMessage
from aiogram.types import CallbackQuery, Chat, Document, File, Message, PhotoSize, Update, User
from django.urls import reverse

from attendance.models import AttendanceRecord, AttendanceStatus as S, Dispute, TelegramLink
from attendance.telegram_bot import make_router, screen

pytestmark = pytest.mark.django_db(transaction=True)


class OfflineSession(BaseSession):
    """Ни один вызов этих тестов не обращается к реальному Telegram."""
    def __init__(self):
        super().__init__()
        self.calls = []
        self.upload = b"offline-certificate"

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Offline", username="offline_bot")
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="proof", file_path="offline/proof.pdf")
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.calls), date=datetime.now(timezone.utc),
                chat=Chat(id=int(method.chat_id), type="private"), text=method.text)
        return True

    async def stream_content(self, url, **kwargs):
        yield self.upload


def client_bot():
    session = OfflineSession()
    bot = Bot(token="123456:offline-test-token", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(make_router())
    return dispatcher, bot, session


async def update(dispatcher, bot, number, text=None, callback=None, document=None, photo=None, caption=None, group=False):
    user = User(id=321, is_bot=False, first_name="Test")
    message = Message(message_id=number, date=datetime.now(timezone.utc),
        chat=Chat(id=-321 if group else 321, type="group" if group else "private"),
        from_user=user, text=text, document=document, photo=photo, caption=caption)
    if callback:
        event = Update(update_id=number, callback_query=CallbackQuery(id=str(number), from_user=user,
            chat_instance="offline", message=message, data=callback))
    else:
        event = Update(update_id=number, message=message)
    await dispatcher.feed_update(bot, event)


def replies(session):
    return [call.text for call in session.calls if isinstance(call, SendMessage)]


@pytest.mark.parametrize("attachment", ["text", "document", "photo"])
def test_bot_request_reaches_assigned_teacher_and_web_decision(client, sample, attachment):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member)
    record.change(S.ABSENT, sample.headman, "", sample.now)
    token = sample.services.telegram_link.create_link_token(sample.member)
    dispatcher, bot, session = client_bot()

    async def scenario():
        await update(dispatcher, bot, 1, text=f"/start {token}")
        await update(dispatcher, bot, 2, callback=f"dispute:{record.pk}")
        if attachment == "text":
            await update(dispatcher, bot, 3, text="Был на занятии")
        elif attachment == "document":
            await update(dispatcher, bot, 3, caption="Справка", document=Document(
                file_id="proof", file_unique_id="proof", file_name="proof.pdf", file_size=19))
        else:
            await update(dispatcher, bot, 3, caption="Фото справки", photo=[PhotoSize(
                file_id="proof", file_unique_id="proof", width=100, height=100, file_size=19)])
        await dispatcher.storage.close()
        await bot.session.close()

    asyncio.run(scenario())
    assert any("отправлена преподавателю" in text for text in replies(session))
    dispute = Dispute.objects.get()
    assert dispute.record_id == record.pk
    if attachment != "text":
        with dispute.attachment.open("rb") as evidence:
            assert evidence.read() == session.upload
    client.force_login(sample.teacher.user)
    page = client.get(reverse("attendance:disputes"))
    assert page.context["page_obj"].object_list[0]["dispute"] == dispute
    response = client.post(reverse("attendance:disputes"), {"action": "fix", "dispute_id": dispute.pk})
    assert response.status_code == 302
    record.refresh_from_db()
    assert record.status == S.PRESENT
    assert record.changes.latest("pk").changed_by == sample.teacher.user


def test_logout_clears_binding_and_blocks_old_callback(sample):
    token = sample.services.telegram_link.create_link_token(sample.member)
    dispatcher, bot, session = client_bot()

    async def scenario():
        await update(dispatcher, bot, 1, text=f"/start {token}")
        await update(dispatcher, bot, 2, text="/logout")
        await update(dispatcher, bot, 3, callback="stats")
        await dispatcher.storage.close()

    asyncio.run(scenario())
    assert not TelegramLink.objects.exists()
    assert any("Вы вышли из аккаунта" in text for text in replies(session))
    assert "Привяжите Telegram" in replies(session)[-1]


def test_private_bot_ignores_group_messages(sample):
    dispatcher, bot, session = client_bot()
    asyncio.run(update(dispatcher, bot, 1, text="/start", group=True))
    assert replies(session) == []
    assert not TelegramLink.objects.exists()


def test_cancel_and_stale_resolve_buttons_do_not_open_or_resolve_request(sample):
    record = AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member, status=S.ABSENT)
    sample.services.telegram_link.bind(sample.services.telegram_link.create_link_token(sample.member), "321")
    dispatcher, bot, session = client_bot()

    async def scenario():
        await update(dispatcher, bot, 1, callback=f"dispute:{record.pk}")
        await update(dispatcher, bot, 2, text="/cancel")
        await update(dispatcher, bot, 3, text="Текст после отмены")
        await update(dispatcher, bot, 4, callback="fix:999999")
        await dispatcher.storage.close()

    asyncio.run(scenario())
    assert not Dispute.objects.exists()
    assert "Решение принимает преподаватель" in replies(session)[-1]


@pytest.mark.parametrize("action,expected", [("today", "✅ Был"), ("week", "✅ Был"),
    ("stats", "Посещаемость за семестр"), ("absences", "сначала недавние"),
    ("disputes", "Мои споры"), ("delegation", "замена старосты"),
    ("notifications", "Уведомления включены")])
def test_bot_sections_use_shared_services(sample, action, expected):
    AttendanceRecord.objects.create(lesson=sample.lesson, student=sample.member, status=S.PRESENT)
    sample.services.telegram_link.bind(sample.services.telegram_link.create_link_token(sample.member), "321")
    text, markup = screen("321", action)
    assert expected in text
    assert markup.inline_keyboard
    if action in ("today", "week"):
        assert "\n\n09:00" in text
