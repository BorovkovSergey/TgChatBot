import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
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

from bot.handlers import (
    LEFT_VOLUNTARILY,
    _is_admin,
    cmd_bantime,
    cmd_start,
    cmd_status,
    on_member_left,
)
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


def make_message(sender_chat=None, from_user=USER, chat=CHAT):
    return Message(
        message_id=1, date=DATE, chat=chat, from_user=from_user, sender_chat=sender_chat
    )


def sent_text(bot):
    method = bot.await_args.args[0]
    return method.text


def restricted(is_member):
    from aiogram.types import ChatMemberRestricted

    return ChatMemberRestricted.model_construct(
        user=USER, status="restricted", is_member=is_member
    )


class TestLeaveFilter:
    def matches(self, old, new):
        event = ChatMemberUpdated(
            chat=CHAT, from_user=USER, date=DATE, old_chat_member=old, new_chat_member=new
        )
        return asyncio.run(LEFT_VOLUNTARILY(event))

    def test_member_left_matches(self):
        assert self.matches(ChatMemberMember(user=USER), ChatMemberLeft(user=USER))

    def test_restricted_member_leaving_matches(self):
        # A muted user who leaves keeps status "restricted", only
        # is_member flips to False — Telegram never sends "left" here.
        assert self.matches(restricted(True), restricted(False))

    def test_kick_does_not_match(self):
        from aiogram.types import ChatMemberBanned

        banned = ChatMemberBanned(user=USER, until_date=DATE)
        assert not self.matches(ChatMemberMember(user=USER), banned)

    def test_mute_does_not_match(self):
        assert not self.matches(ChatMemberMember(user=USER), restricted(True))


class TestOnMemberLeft:
    def test_leaver_banned_and_announced(self, tmp_path):
        bot = AsyncMock()
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_awaited_once_with(
            CHAT.id, USER.id, until_date=timedelta(seconds=86400)
        )
        args = bot.send_message.await_args.args
        assert "бан на 1d" in args[1]

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

    def test_leaving_restricted_member_banned(self, tmp_path):
        from aiogram.types import ChatMemberRestricted

        bot = AsyncMock()
        restricted = ChatMemberRestricted.model_construct(
            user=USER, status="restricted", is_member=True
        )
        event = ChatMemberUpdated(
            chat=CHAT,
            from_user=USER,
            date=DATE,
            old_chat_member=restricted,
            new_chat_member=ChatMemberLeft(user=USER),
        )
        asyncio.run(on_member_left(event, bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_awaited_once()

    def test_custom_ban_duration_used(self, tmp_path):
        from bot.settings import ChatSettings

        bot = AsyncMock()
        store = make_store(tmp_path)
        store.set(CHAT.id, ChatSettings(ban_seconds=3600))
        asyncio.run(on_member_left(leave_event(), bot, store))
        bot.ban_chat_member.assert_awaited_once_with(
            CHAT.id, USER.id, until_date=timedelta(seconds=3600)
        )
        assert "бан на 1h" in bot.send_message.await_args.args[1]

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
        assert "покинул(а) чат" in text
        assert "без бана" in text

    def test_send_failure_does_not_raise(self, tmp_path):
        bot = AsyncMock()
        bot.send_message.side_effect = API_ERROR
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))

    def _patch_sleep(self, monkeypatch):
        sleeps = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr("bot.handlers.asyncio.sleep", fake_sleep)
        return sleeps

    def test_ban_retried_after_flood_limit(self, tmp_path, monkeypatch):
        self._patch_sleep(monkeypatch)
        bot = AsyncMock()
        flood = TelegramRetryAfter(method=None, message="flood", retry_after=1)
        bot.ban_chat_member.side_effect = [flood, None]
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        assert bot.ban_chat_member.await_count == 2
        assert "бан на" in bot.send_message.await_args.args[1]

    def test_ban_retry_failure_blames_flood_not_rights(self, tmp_path, monkeypatch):
        self._patch_sleep(monkeypatch)
        bot = AsyncMock()
        flood = TelegramRetryAfter(method=None, message="flood", retry_after=1)
        bot.ban_chat_member.side_effect = [flood, flood]
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        assert bot.ban_chat_member.await_count == 2
        text = bot.send_message.await_args.args[1]
        assert "флуд" in text.lower()
        assert "права" not in text.lower()

    def test_ban_locks_are_per_chat(self):
        from bot.handlers import _ban_locks

        try:
            assert _ban_locks[-1] is _ban_locks[-1]
            assert _ban_locks[-1] is not _ban_locks[-2]
        finally:
            _ban_locks.pop(-1, None)
            _ban_locks.pop(-2, None)

    def test_basic_group_leaver_not_banned(self, tmp_path):
        # until_date works only in supergroups/channels; a ban in a basic
        # group would silently become permanent
        bot = AsyncMock()
        group = Chat(id=-200, type="group")
        event = ChatMemberUpdated(
            chat=group,
            from_user=USER,
            date=DATE,
            old_chat_member=ChatMemberMember(user=USER),
            new_chat_member=ChatMemberLeft(user=USER),
        )
        asyncio.run(on_member_left(event, bot, make_store(tmp_path)))
        bot.ban_chat_member.assert_not_awaited()
        assert "супергрупп" in bot.send_message.await_args.args[1]

    def test_ban_retry_sleep_capped_with_jitter(self, tmp_path, monkeypatch):
        # N parallel handlers must not retry in lockstep with a huge delay
        sleeps = self._patch_sleep(monkeypatch)
        bot = AsyncMock()
        flood = TelegramRetryAfter(method=None, message="flood", retry_after=500)
        bot.ban_chat_member.side_effect = [flood, None]
        asyncio.run(on_member_left(leave_event(), bot, make_store(tmp_path)))
        assert sleeps
        assert 60 <= sleeps[0] <= 61


class TestMigration:
    def test_settings_follow_supergroup_upgrade(self, tmp_path):
        from bot.handlers import on_migrate
        from bot.settings import ChatSettings

        store = make_store(tmp_path)
        store.set(CHAT.id, ChatSettings(ban_seconds=3600))
        message = Message(
            message_id=1,
            date=DATE,
            chat=CHAT,
            from_user=USER,
            migrate_to_chat_id=-100999,
        )
        asyncio.run(on_migrate(message, store))
        assert store.get(-100999).ban_seconds == 3600
        assert CHAT.id not in store._settings

    def test_migration_noop_without_settings(self, tmp_path):
        from bot.handlers import on_migrate

        store = make_store(tmp_path)
        message = Message(
            message_id=1,
            date=DATE,
            chat=CHAT,
            from_user=USER,
            migrate_to_chat_id=-100999,
        )
        asyncio.run(on_migrate(message, store))
        assert -100999 not in store._settings


class TestPrivateStart:
    def test_start_points_to_group_setup(self):
        bot = AsyncMock()
        private_chat = Chat(id=42, type="private")
        message = Message(
            message_id=1, date=DATE, chat=private_chat, from_user=USER, text="/start"
        ).as_(bot)
        asyncio.run(cmd_start(message))
        assert "групп" in sent_text(bot)

    def test_other_private_messages_get_fallback(self):
        from bot.handlers import private_fallback

        bot = AsyncMock()
        private_chat = Chat(id=42, type="private")
        message = Message(
            message_id=1, date=DATE, chat=private_chat, from_user=USER, text="/status"
        ).as_(bot)
        asyncio.run(private_fallback(message))
        assert "в группе" in sent_text(bot)


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

    def test_message_without_user_rejected_with_reply(self, tmp_path):
        bot = AsyncMock()
        message = make_message(from_user=None).as_(bot)
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

    def test_reply_failure_does_not_raise(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        bot.side_effect = API_ERROR  # every bound-method call fails
        message = make_message().as_(bot)
        asyncio.run(cmd_status(message, bot, make_store(tmp_path)))

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
    def test_bantime_warns_when_save_fails(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        store = make_store(tmp_path)
        tmp_path.chmod(0o500)
        try:
            message = make_message().as_(bot)
            command = CommandObject(command="bantime", args="2h")
            asyncio.run(cmd_bantime(message, command, bot, store))
            text = sent_text(bot)
            assert "Срок бана установлен" in text
            assert "не сохранил" in text.lower()
        finally:
            tmp_path.chmod(0o700)

    def test_bantime_warns_in_basic_group(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        group = Chat(id=-200, type="group")
        message = make_message(chat=group).as_(bot)
        command = CommandObject(command="bantime", args="2h")
        asyncio.run(cmd_bantime(message, command, bot, make_store(tmp_path)))
        text = sent_text(bot)
        assert "Срок бана установлен" in text
        assert "супергрупп" in text

    def test_status_warns_in_basic_group(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        group = Chat(id=-200, type="group")
        message = make_message(chat=group).as_(bot)
        asyncio.run(cmd_status(message, bot, make_store(tmp_path)))
        assert "супергрупп" in sent_text(bot)

    def test_bantime_no_warning_in_supergroup(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        message = make_message().as_(bot)
        command = CommandObject(command="bantime", args="2h")
        asyncio.run(cmd_bantime(message, command, bot, make_store(tmp_path)))
        assert "супергрупп" not in sent_text(bot)

    def test_bantime_rejects_bad_duration(self, tmp_path):
        bot = AsyncMock()
        bot.get_chat_member.return_value = ADMIN
        store = make_store(tmp_path)
        message = make_message().as_(bot)
        command = CommandObject(command="bantime", args="5s")
        asyncio.run(cmd_bantime(message, command, bot, store))
        assert store.get(CHAT.id).ban_seconds == 86400
