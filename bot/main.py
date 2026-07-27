"""Entry point: bot setup and long polling."""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import router
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

    # Without "chat_member" in allowed_updates Telegram never delivers
    # member-leave events, even to an admin bot.
    await dp.start_polling(bot, allowed_updates=["message", "chat_member"])


if __name__ == "__main__":
    asyncio.run(main())
