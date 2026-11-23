"""Handlers: leave tracking with auto-ban, admin commands."""

import asyncio
import logging
import random
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import DefaultDict, Dict, List, Tuple, Union

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import (
    IS_MEMBER,
    LEFT,
    RESTRICTED,
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


async def _announce(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except TelegramAPIError as e:
        logger.warning("Failed to announce in chat %s: %s", chat_id, e)


async def _reply(message: Message, text: str) -> None:
    try:
        await message.reply(text)
    except TelegramAPIError as e:
        logger.warning("Failed to reply in chat %s: %s", message.chat.id, e)


# Polling handles updates as parallel tasks: on a mass leave every handler
# would hit flood control, sleep the same retry_after and retry in lockstep.
# Per-chat locks serialize bans within a chat (Telegram flood limits are
# mostly per-chat), the cap and jitter spread the retries out.
# Entries are never removed: growth is bounded by the number of chats, and
# safe removal would need CPython lock internals (_waiters) with no contract.
_ban_locks: DefaultDict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_RETRY_AFTER_CAP = 60


async def _ban_with_retry(
    bot: Bot, chat_id: int, user_id: int, until: Union[timedelta, datetime]
) -> None:
    async with _ban_locks[chat_id]:
        try:
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        except TelegramRetryAfter as e:
            delay = min(e.retry_after, _RETRY_AFTER_CAP) + random.uniform(0, 1)
            logger.info(
                "Flood limit banning %s in %s, retrying in %.1fs",
                user_id,
                chat_id,
                delay,
            )
            await asyncio.sleep(delay)
            await bot.ban_chat_member(chat_id, user_id, until_date=until)


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError as e:
        logger.warning("get_chat_member(%s, %s) failed: %s", chat_id, user_id, e)
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


# A restricted (muted) user who leaves keeps status "restricted" with
# is_member=False instead of "left", hence -RESTRICTED. "kicked" stays
# excluded: the admin already banned that user.
LEFT_VOLUNTARILY = ChatMemberUpdatedFilter(IS_MEMBER >> (LEFT | -RESTRICTED))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Telegram keeps updates queued for up to 24h while the bot is down. Replaying
# that backlog one event at a time would re-ban a user who left N times N
# times and post N announcements, all dated "now". Instead stale leaves are
# collected per chat until the backlog stops arriving, then each user is
# banned once, counted from their LAST leave, with one summary message.
_STALE_AFTER = timedelta(minutes=1)
_STALE_QUIET = 5.0  # seconds without new stale leaves before flushing a chat
# Telegram treats until_date closer than 30s from now as a permanent ban
_MIN_BAN_LEFT = timedelta(minutes=1)
_stale_leaves: Dict[int, Dict[int, Tuple[User, datetime]]] = {}
_stale_flushers: Dict[int, "asyncio.Task[None]"] = {}


def _queue_stale_leave(
    bot: Bot, chat_id: int, user: User, left_at: datetime, store: SettingsStore
) -> None:
    pending = _stale_leaves.setdefault(chat_id, {})
    known = pending.get(user.id)
    if known is None or left_at > known[1]:
        pending[user.id] = (user, left_at)
    # Debounce: restart the timer on every new stale leave. A flusher that is
    # already past its sleep has detached its batch, so cancelling only ever
    # hits one that is still waiting.
    flusher = _stale_flushers.get(chat_id)
    if flusher is not None:
        flusher.cancel()
    _stale_flushers[chat_id] = asyncio.create_task(
        _flush_stale_leaves(bot, chat_id, store)
    )


async def _flush_stale_leaves(bot: Bot, chat_id: int, store: SettingsStore) -> None:
    await asyncio.sleep(_STALE_QUIET)
    # Detach the batch atomically (no await in between): later stale leaves
    # start a new batch with a new flusher.
    pending = _stale_leaves.pop(chat_id, {})
    if _stale_flushers.get(chat_id) is asyncio.current_task():
        del _stale_flushers[chat_id]
    ban = timedelta(seconds=store.get(chat_id).ban_seconds)
    lines: List[str] = []
    for user, left_at in pending.values():
        until = left_at + ban
        if until - _now() < _MIN_BAN_LEFT:
            continue  # the ban would already be over
        try:
            await _ban_with_retry(bot, chat_id, user.id, until)
        except TelegramAPIError as e:
            logger.warning("Failed to ban %s in %s: %s", user.id, chat_id, e)
            lines.append(
                f"{user.mention_html()} — не смог забанить, "
                f"проверь права бота (детали в логах)."
            )
        else:
            lines.append(f"{user.mention_html()} — бан до {until:%d.%m %H:%M} UTC.")
    if lines:
        await _announce(
            bot,
            chat_id,
            "Пока бот был недоступен, из чата вышли:\n" + "\n".join(lines),
        )


@router.chat_member(LEFT_VOLUNTARILY)
async def on_member_left(event: ChatMemberUpdated, bot: Bot, store: SettingsStore) -> None:
    user: User = event.old_chat_member.user
    if user.is_bot:
        return
    if _now() - event.date > _STALE_AFTER:
        # Admins are never banned and basic groups cannot hold a temporary
        # ban: a replayed backlog only produces noise for them, skip silently.
        if event.chat.type != ChatType.GROUP and event.old_chat_member.status not in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        ):
            _queue_stale_leave(bot, event.chat.id, user, event.date, store)
        return
    if event.old_chat_member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ):
        await _announce(
            bot,
            event.chat.id,
            f"{user.mention_html()} покинул(а) чат (админ — без бана).",
        )
        return
    if event.chat.type == ChatType.GROUP:
        # until_date applies only in supergroups/channels; here the ban
        # would silently become permanent while we promise a temporary one
        await _announce(
            bot,
            event.chat.id,
            f"{user.mention_html()} покинул(а) чат. Не баню: обычная группа "
            f"не поддерживает временный бан — преобразуй её в супергруппу.",
        )
        return
    ban_seconds = store.get(event.chat.id).ban_seconds
    try:
        await _ban_with_retry(
            bot, event.chat.id, user.id, timedelta(seconds=ban_seconds)
        )
    except TelegramRetryAfter as e:
        logger.warning("Flood limit banning %s in %s: %s", user.id, event.chat.id, e)
        text = (
            f"{user.mention_html()} покинул(а) чат. "
            f"Не забанил из-за флуд-лимита Telegram — забань вручную."
        )
    except TelegramAPIError as e:
        logger.warning("Failed to ban %s in %s: %s", user.id, event.chat.id, e)
        text = (
            f"{user.mention_html()} покинул(а) чат. "
            f"Не смог забанить — проверь права бота (детали в логах)."
        )
    else:
        text = (
            f"{user.mention_html()} покинул(а) чат — "
            f"бан на {format_duration(ban_seconds)}."
        )
    await _announce(bot, event.chat.id, text)


@router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message, store: SettingsStore) -> None:
    # Group upgraded to supergroup: chat id changes, carry the settings over.
    store.migrate(message.chat.id, message.migrate_to_chat_id)


# Settings still get saved in a basic group: they carry over via on_migrate
# once the group is upgraded.
_BASIC_GROUP_WARNING = (
    "\n⚠️ Это обычная группа — временный бан здесь не работает, "
    "преобразуй её в супергруппу."
)


def _group_warning(message: Message) -> str:
    return _BASIC_GROUP_WARNING if message.chat.type == ChatType.GROUP else ""


async def _require_admin(message: Message, bot: Bot) -> bool:
    # Anonymous chat admins post on behalf of the chat itself.
    if message.sender_chat is not None and message.sender_chat.id == message.chat.id:
        return True
    if message.from_user is None or not await _is_admin(
        bot, message.chat.id, message.from_user.id
    ):
        await _reply(message, "Команда только для админов.")
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
        await _reply(message, f"{e}. Использование: /bantime 30m|2h|3d")
        return
    saved = store.set(
        message.chat.id, replace(store.get(message.chat.id), ban_seconds=seconds)
    )
    text = f"Срок бана установлен: {format_duration(seconds)}"
    if not saved:
        text += "\n⚠️ Не сохранилось на диск — после рестарта бота настройка пропадёт."
    await _reply(message, text + _group_warning(message))


@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot, store: SettingsStore) -> None:
    if not await _require_admin(message, bot):
        return
    await _reply(
        message,
        f"Срок бана: {format_duration(store.get(message.chat.id).ban_seconds)}"
        + _group_warning(message),
    )


private_router = Router()
private_router.message.filter(F.chat.type == ChatType.PRIVATE)


@private_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await _reply(
        message,
        "Я слежу за вышедшими из группы и баню их на время.\n"
        "Добавь меня в группу и назначь админом с правом «Ban users».\n"
        "Команды в группе (для админов): /bantime 2h, /status.",
    )


@private_router.message()
async def private_fallback(message: Message) -> None:
    await _reply(message, "Команды работают только в группе. Инструкция: /start")
