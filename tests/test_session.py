import json

import pytest

from aiogram import Bot
from aiogram.exceptions import ClientDecodeError
from aiogram.methods import GetMe, GetUpdates

from bot.session import TolerantSession

BOT = Bot("123:TEST")
CHAT = {"id": -100500, "type": "supergroup"}


def message_update(update_id, **extra):
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "date": 1, "chat": CHAT, **extra},
    }


# A block type from a future Bot API version this aiogram does not know
FUTURE = {"rich_message": {"blocks": [{"type": "zzz_future_block"}]}}


def check(method, payload):
    content = json.dumps(payload)
    return TolerantSession().check_response(BOT, method, 200, content)


def test_unparseable_update_replaced_with_stub():
    payload = {
        "ok": True,
        "result": [message_update(1), message_update(2, **FUTURE), message_update(3)],
    }
    updates = check(GetUpdates(), payload).result
    assert [u.update_id for u in updates] == [1, 2, 3]
    assert updates[0].message is not None
    assert updates[1].message is None  # dropped, but offset still advances
    assert updates[2].message is not None


def test_valid_updates_parsed_as_is():
    payload = {"ok": True, "result": [message_update(1)]}
    updates = check(GetUpdates(), payload).result
    assert updates[0].message.chat.id == CHAT["id"]


def test_other_methods_still_fail_loudly():
    payload = {"ok": True, "result": {"id": "not-an-int"}}
    with pytest.raises(ClientDecodeError):
        check(GetMe(), payload)


def test_error_response_without_result_still_raises():
    from aiogram.exceptions import TelegramBadRequest

    payload = {"ok": False, "error_code": 400, "description": "Bad Request: nope"}
    with pytest.raises(TelegramBadRequest):
        TolerantSession().check_response(BOT, GetUpdates(), 400, json.dumps(payload))
