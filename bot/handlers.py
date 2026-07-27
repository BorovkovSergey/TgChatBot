"""Handlers: leave tracking, ban buttons, admin commands."""

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
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

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


async def _ban(bot: Bot, chat_id: int, user_id: int, mention: str, ban_seconds: int) -> str:
    try:
        await bot.ban_chat_member(
            chat_id, user_id, until_date=timedelta(seconds=ban_seconds)
        )
    except TelegramAPIError as e:
        logger.warning("Failed to ban %s in %s: %s", user_id, chat_id, e)
        return f"Не смог забанить {mention}: {e.message}"
    return f"{mention} забанен на {format_duration(ban_seconds)}."


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> LEFT))
async def on_member_left(event: ChatMemberUpdated, bot: Bot, store: SettingsStore) -> None:
    user: User = event.old_chat_member.user
    if user.is_bot:
        return
    settings = store.get(event.chat.id)
    if settings.mode == "auto":
        text = await _ban(bot, event.chat.id, user.id, user.mention_html(), settings.ban_seconds)
        await bot.send_message(event.chat.id, f"{user.mention_html()} вышел из чата. {text}")
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Забанить на {format_duration(settings.ban_seconds)}",
                        callback_data=f"ban:{user.id}",
                    ),
                    InlineKeyboardButton(text="Пропустить", callback_data=f"skip:{user.id}"),
                ]
            ]
        )
        await bot.send_message(
            event.chat.id,
            f"{user.mention_html()} вышел из чата.",
            reply_markup=keyboard,
        )


@router.callback_query(F.data.startswith("ban:") | F.data.startswith("skip:"))
async def on_ban_button(query: CallbackQuery, bot: Bot, store: SettingsStore) -> None:
    message = query.message
    if not isinstance(message, Message):
        await query.answer("Сообщение недоступно", show_alert=True)
        return
    if not await _is_admin(bot, message.chat.id, query.from_user.id):
        await query.answer("Кнопка только для админов", show_alert=True)
        return

    action, user_id = query.data.split(":", 1)
    if not user_id.isdigit():
        await query.answer("Некорректные данные кнопки", show_alert=True)
        return
    admin = query.from_user.full_name
    if action == "ban":
        settings = store.get(message.chat.id)
        result = await _ban(bot, message.chat.id, int(user_id), "пользователь", settings.ban_seconds)
        new_text = f"{message.html_text}\n{result} (админ: {admin})"
    else:
        new_text = f"{message.html_text}\nПропущен (админ: {admin})."
    try:
        await message.edit_text(new_text)
    except TelegramAPIError as e:
        logger.warning("edit_text failed in chat %s: %s", message.chat.id, e)
    await query.answer()


async def _require_admin(message: Message, bot: Bot) -> bool:
    if message.from_user is None:
        return False
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Команда только для админов.")
        return False
    return True


@router.message(Command("banmode"))
async def cmd_banmode(
    message: Message, command: CommandObject, bot: Bot, store: SettingsStore
) -> None:
    if not await _require_admin(message, bot):
        return
    mode = (command.args or "").strip().lower()
    if mode not in ("auto", "manual"):
        await message.reply("Использование: /banmode auto|manual")
        return
    store.set(message.chat.id, replace(store.get(message.chat.id), mode=mode))
    await message.reply(f"Режим установлен: {mode}")


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
    settings = store.get(message.chat.id)
    await message.reply(
        f"Режим: {settings.mode}\nСрок бана: {format_duration(settings.ban_seconds)}"
    )
