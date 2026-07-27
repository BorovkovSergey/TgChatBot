"""Entry point: bot setup and long polling."""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators

from bot.handlers import private_router, router
from bot.settings import SettingsStore


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("BOT_TOKEN")
    if not token:
        sys.exit("BOT_TOKEN environment variable is not set")

    store = SettingsStore(os.environ.get("SETTINGS_PATH", "data/settings.json"))
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(store=store)
    dp.include_router(router)
    dp.include_router(private_router)

    # The command menu is a nicety: a startup hiccup here must not crash the
    # bot into a docker restart loop.
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="bantime", description="Срок бана: 30m, 2h, 3d"),
                BotCommand(command="status", description="Текущие настройки"),
            ],
            scope=BotCommandScopeAllChatAdministrators(),
        )
    except TelegramAPIError as e:
        logging.getLogger(__name__).warning("set_my_commands failed: %s", e)

    # Derived from registered handlers; must include "chat_member", without
    # it Telegram never delivers member-leave events, even to an admin bot.
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
