import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.types import (
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberUpdated,
    Message,
    User,
)

from bot.handlers import _is_admin, cmd_bantime, cmd_status, on_member_left
from bot.settings import SettingsStore

DATE = datetime(2026, 1, 1)
CHAT = Chat(id=-100500, type="supergroup")
USER = User(id=42, is_bot=False, first_name="Vasya")
ADMIN = ChatMemberOwner(user=USER, is_anonymous=False)
API_ERROR = TelegramBadRequest(method=None, message="Not enough rights")


def make_store(tmp_path):
    return SettingsStore(tmp_path / "settings.json")


def leave_event(user=USER):
    return ChatMemberUpdated(
        chat=CHAT,
        from_user=user,
        date=DATE,
        old_chat_member=ChatMemberMember(user=user),
        new_chat_member=ChatMemberLeft(user=user),
    )


def make_message(sender_chat=None):
    return Message(
        message_id=1, date=DATE, chat=CHAT, from_user=USER, sender_chat=sender_chat
    )


def sent_text(bot):
    method = bot.await_args.args[0]
    return method.text


class TestOnMemberLeft:
    def test_leaver_banned_and_announced(self, tmp_path):
        bot = AsyncMock()
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_awaited_once_with(
            CHAT.id, USER.id, until_date=timedelta(seconds=86400)
        )
        args = bot.send_message.await_args.args
        assert "Забанен на 1d" in args[1]

    def test_leaving_bot_ignored(self, tmp_path):
        bot = AsyncMock()
        event = leave_event(User(id=7, is_bot=True, first_name="SomeBot"))
        asyncio.run(on_member_left(event, bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    def test_ban_failure_announced(self, tmp_path):
        bot = AsyncMock()
        bot.ban_chat_member.side_effect = API_ERROR
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        text = bot.send_message.await_args.args[1]
        assert "Не смог забанить" in text
        assert "Not enough rights" not in text  # raw API details stay in logs

    def test_leaving_admin_not_banned(self, tmp_path):
        bot = AsyncMock()
        event = ChatMemberUpdated(
            chat=CHAT,
            from_user=USER,
            date=DATE,
            old_chat_member=ADMIN,
            new_chat_member=ChatMemberLeft(user=USER),
        )
        asyncio.run(on_member_left(event, bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_not_awaited()
        text = bot.send_message.await_args.args[1]
        assert "вышел из чата" in text
        assert "Забанен" not in text

    def test_send_failure_does_not_raise(self, tmp_path):
        bot = AsyncMock()
        bot.send_message.side_effect = API_ERROR
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))


class TestIsAdmin:
    def test_owner_is_admin(self):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        assert asyncio.run(_is_admin(bot, CHAT.id, USER.id))

    def test_member_is_not_admin(self):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ChatMemberMember(user=USER)
        assert not asyncio.run(_is_admin(bot, CHAT.id, USER.id))

    def test_api_error_means_not_admin(self):
        bot = AsyncMock()
        bot.get_chat_member.side_effect = API_ERROR
        assert not asyncio.run(_is_admin(bot, CHAT.id, USER.id))


class TestCommands:
    def test_non_admin_rejected(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ChatMemberMember(user=USER)
        message = make_message().as_(bot)
        asyncio.run(cmd_status(message, bot, make_store(tmp_path)))
        assert "только для админов" in sent_text(bot)

    def test_anonymous_admin_allowed(self, tmp_path):
        bot = AsyncMock()
        message = make_message(sender_chat=CHAT).as_(bot)
        asyncio.run(cmd_status(message, bot, make_store(tmp_path)))
        bot.get_chat_member.assert_not_awaited()
        assert "Срок бана" in sent_text(bot)

    def test_bantime_updates_store(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        store = make_store(tmp_path)
        message = make_message().as_(bot)
        command = CommandObject(command="bantime", args="2h")
        asyncio.run(cmd_bantime(message, command, bot, store))
        assert store.get(CHAT.id).ban_seconds == 7200

    def test_bantime_rejects_bad_duration(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        store = make_store(tmp_path)
        message = make_message().as_(bot)
        command = CommandObject(command="bantime", args="5s")
        asyncio.run(cmd_bantime(message, command, bot, store))
        assert store.get(CHAT.id).ban_seconds == 86400
