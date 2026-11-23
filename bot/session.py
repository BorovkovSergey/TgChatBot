"""HTTP session that survives updates the installed aiogram cannot parse."""

import json
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import ClientDecodeError
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import Update
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class TolerantSession(AiohttpSession):
    """aiogram parses a getUpdates batch as one model: a single update with a
    type from a newer Bot API (e.g. an unknown rich_message block) fails the
    whole batch, the offset never advances and polling retries the same batch
    forever. Here each unparseable update is replaced with a bare
    {"update_id": N}: the dispatcher skips it as an unknown update type and
    the offset moves on.

    Trade-off: the replaced update is lost entirely, whatever it carried.
    """

    def check_response(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        status_code: int,
        content: str,
    ) -> Response[TelegramType]:
        try:
            return super().check_response(bot, method, status_code, content)
        except ClientDecodeError:
            if not isinstance(method, GetUpdates):
                raise
            sanitized = self._sanitize_updates(bot, content)
            if sanitized is None:
                raise
        return super().check_response(bot, method, status_code, sanitized)

    @staticmethod
    def _sanitize_updates(bot: Bot, content: str) -> "str | None":
        """Return content with unparseable updates stubbed out, or None when
        the failure is not about individual updates."""
        try:
            data: Any = json.loads(content)
        except ValueError:
            return None
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, list):
            return None
        replaced = 0
        for i, raw in enumerate(result):
            if not isinstance(raw, dict) or not isinstance(raw.get("update_id"), int):
                return None  # cannot stub without an id to advance past
            try:
                Update.model_validate(raw, context={"bot": bot})
            except ValidationError as e:
                logger.warning(
                    "Skipping update %d: this aiogram cannot parse it: %s",
                    raw["update_id"],
                    "; ".join(
                        f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
                        for err in e.errors()
                    ),
                )
                result[i] = {"update_id": raw["update_id"]}
                replaced += 1
        if not replaced:
            return None
        return json.dumps(data)
