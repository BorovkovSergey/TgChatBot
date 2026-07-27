"""Per-chat settings storage and ban-duration parsing."""

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict

# Telegram treats until_date outside this range as a permanent ban.
MIN_BAN_SECONDS = 30
MAX_BAN_SECONDS = 366 * 86400

DEFAULT_MODE = "manual"
DEFAULT_BAN_SECONDS = 86400

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)


class DurationError(ValueError):
    pass


def parse_duration(text: str) -> int:
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise DurationError(
            "Неверный формат срока. Примеры: 30s, 45m, 2h, 3d"
        )
    seconds = int(match.group(1)) * _UNITS[match.group(2).lower()]
    if not MIN_BAN_SECONDS <= seconds <= MAX_BAN_SECONDS:
        raise DurationError("Срок должен быть от 30 секунд до 366 дней")
    return seconds


def format_duration(seconds: int) -> str:
    parts = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{unit}")
    return " ".join(parts) if parts else "0s"


@dataclass
class ChatSettings:
    mode: str = DEFAULT_MODE  # "auto" | "manual"
    ban_seconds: int = DEFAULT_BAN_SECONDS


class SettingsStore:
    def __init__(self, path):
        self._path = Path(path)
        self._settings: Dict[int, ChatSettings] = self._load()

    def get(self, chat_id: int) -> ChatSettings:
        return self._settings.get(chat_id, ChatSettings())

    def set(self, chat_id: int, settings: ChatSettings) -> None:
        self._settings[chat_id] = settings
        self._save()

    def _load(self) -> Dict[int, ChatSettings]:
        try:
            raw = json.loads(self._path.read_text())
            return {int(chat_id): ChatSettings(**data) for chat_id, data in raw.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {str(chat_id): asdict(s) for chat_id, s in self._settings.items()}
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._path)
        except BaseException:
            os.unlink(tmp)
            raise
