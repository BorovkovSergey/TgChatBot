"""Handlers: leave tracking with auto-ban, admin commands."""

import logging
from dataclasses import replace
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import (
    IS_MEMBER,
    LEFT,
    ChatMemberUpdatedFilter,
    Command,
    CommandObject,
)
from aiogram.types import ChatMemberUpdated, Message, User

from bot.settings import (
    DurationError,
    SettingsStore,
    format_duration,
    parse_duration,
)

logger = logging.getLogger(__name__)

router = Router()
_GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}
router.message.filter(F.chat.type.in_(_GROUPS))
router.chat_member.filter(F.chat.type.in_(_GROUPS))


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError as e:
        logger.warning("get_chat_member(%s, %s) failed: %s", chat_id, user_id, e)
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> LEFT))
async def on_member_left(event: ChatMemberUpdated, bot: Bot, store: SettingsStore) -> None:
    user: User = event.old_chat_member.user
    if user.is_bot:
        return
    if event.old_chat_member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ):
        text = f"{user.mention_html()} вышел из чата (был админом — без бана)."
        try:
            await bot.send_message(event.chat.id, text)
        except TelegramAPIError as e:
            logger.warning("Failed to announce in chat %s: %s", event.chat.id, e)
        return
    ban_seconds = store.get(event.chat.id).ban_seconds
    try:
        await bot.ban_chat_member(
            event.chat.id, user.id, until_date=timedelta(seconds=ban_seconds)
        )
    except TelegramAPIError as e:
        logger.warning("Failed to ban %s in %s: %s", user.id, event.chat.id, e)
        text = (
            f"{user.mention_html()} вышел из чата. "
            f"Не смог забанить — проверь права бота (детали в логах)."
        )
    else:
        text = (
            f"{user.mention_html()} вышел из чата. "
            f"Забанен на {format_duration(ban_seconds)}."
        )
    try:
        await bot.send_message(event.chat.id, text)
    except TelegramAPIError as e:
        logger.warning("Failed to announce in chat %s: %s", event.chat.id, e)


async def _require_admin(message: Message, bot: Bot) -> bool:
    # Anonymous chat admins post on behalf of the chat itself.
    if message.sender_chat is not None and message.sender_chat.id == message.chat.id:
        return True
    if message.from_user is None:
        return False
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Команда только для админов.")
        return False
    return True


@router.message(Command("bantime"))
async def cmd_bantime(
    message: Message, command: CommandObject, bot: Bot, store: SettingsStore
) -> None:
    if not await _require_admin(message, bot):
        return
    try:
        seconds = parse_duration(command.args or "")
    except DurationError as e:
        await message.reply(f"{e}. Использование: /bantime 30m|2h|3d")
        return
    store.set(message.chat.id, replace(store.get(message.chat.id), ban_seconds=seconds))
    await message.reply(f"Срок бана установлен: {format_duration(seconds)}")


@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot, store: SettingsStore) -> None:
    if not await _require_admin(message, bot):
        return
    await message.reply(
        f"Срок бана: {format_duration(store.get(message.chat.id).ban_seconds)}"
    )
