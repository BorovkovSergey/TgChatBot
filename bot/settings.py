"""Per-chat settings storage and ban-duration parsing."""

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Union

logger = logging.getLogger(__name__)

# Telegram treats until_date outside 30s..366d as a permanent ban. Both
# bounds keep a margin: near the limits, network latency and clock skew
# between the host and Telegram can push until_date over the edge and make
# the ban permanent.
MIN_BAN_SECONDS = 60
MAX_BAN_SECONDS = 365 * 86400

DEFAULT_BAN_SECONDS = 86400

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)


class DurationError(ValueError):
    pass


def parse_duration(text: str) -> int:
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise DurationError(
            "Неверный формат срока. Примеры: 90s, 45m, 2h, 3d"
        )
    seconds = int(match.group(1)) * _UNITS[match.group(2).lower()]
    if not MIN_BAN_SECONDS <= seconds <= MAX_BAN_SECONDS:
        raise DurationError("Срок должен быть от 1 минуты до 365 дней")
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
    ban_seconds: int = DEFAULT_BAN_SECONDS


class SettingsStore:
    def __init__(self, path: Union[str, "os.PathLike[str]"]):
        self._path = Path(path)
        self._cleanup_stale_tmp()
        self._settings: Dict[int, ChatSettings] = self._load()

    def _cleanup_stale_tmp(self) -> None:
        # Leftovers from _save() interrupted between mkstemp and os.replace.
        if not self._path.parent.is_dir():
            return
        for stale in self._path.parent.glob("settings-*.tmp"):
            try:
                stale.unlink()
            except OSError as e:
                logger.warning("Cannot remove stale %s: %s", stale, e)

    def get(self, chat_id: int) -> ChatSettings:
        return self._settings.get(chat_id, ChatSettings())

    def set(self, chat_id: int, settings: ChatSettings) -> bool:
        """Returns False when the new value could not be persisted to disk."""
        self._settings[chat_id] = settings
        try:
            self._save()
        except OSError as e:
            logger.error("Cannot persist settings to %s: %s", self._path, e)
            return False
        return True

    def migrate(self, old_chat_id: int, new_chat_id: int) -> None:
        """Move settings when a group is upgraded and its chat id changes."""
        entry = self._settings.pop(old_chat_id, None)
        if entry is None:
            return
        self.set(new_chat_id, entry)

    def _load(self) -> Dict[int, ChatSettings]:
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            return {}
        except OSError as e:
            # Fail fast: starting with an empty store on a transient read
            # error (EACCES, EIO on a bind mount) would let the first save
            # wipe every other chat's settings that are intact on disk.
            logger.error("Cannot read %s: %s", self._path, e)
            raise
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
        except ValueError as e:
            backup = self._path.with_name(self._path.name + ".bak")
            if backup.exists():
                # Keep the oldest corrupt snapshot — it is closest to the
                # last good state.
                logger.warning(
                    "Corrupt settings file %s (%s); backup %s already exists, "
                    "keeping the older one",
                    self._path,
                    e,
                    backup,
                )
                return {}
            logger.warning(
                "Corrupt settings file %s (%s), moving it to %s", self._path, e, backup
            )
            try:
                os.replace(self._path, backup)
            except OSError as move_error:
                logger.warning("Cannot back up %s: %s", self._path, move_error)
            return {}

        settings = {}
        for chat_id, data in raw.items():
            try:
                entry = ChatSettings(**data)
                if isinstance(entry.ban_seconds, bool) or not isinstance(
                    entry.ban_seconds, int
                ):
                    raise ValueError(f"ban_seconds {entry.ban_seconds!r} is not int")
                if not MIN_BAN_SECONDS <= entry.ban_seconds <= MAX_BAN_SECONDS:
                    raise ValueError(f"ban_seconds {entry.ban_seconds!r} out of range")
                settings[int(chat_id)] = entry
            except (TypeError, ValueError) as e:
                logger.warning("Skipping bad settings entry %r: %s", chat_id, e)
        return settings

    def _save(self) -> None:
        # Deliberately synchronous (blocks the event loop for the write and
        # two fsyncs): the single-threaded loop is what serializes store
        # access. Offloading to a thread would trade a rare millisecond-level
        # pause on a tiny file for real concurrent-write races.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {str(chat_id): asdict(s) for chat_id, s in self._settings.items()}
        # Own prefix so startup cleanup never touches foreign temp files if
        # SETTINGS_PATH ever points into a shared directory.
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, prefix="settings-", suffix=".tmp"
        )
        try:
            f = os.fdopen(fd, "w")
        except BaseException:
            os.close(fd)
            self._discard(tmp)
            raise
        try:
            with f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            self._fsync_dir()
        except BaseException:
            self._discard(tmp)
            raise

    def _fsync_dir(self) -> None:
        # Persist the rename itself: without this a power loss right after
        # os.replace can roll the directory entry back to the old file.
        dir_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @staticmethod
    def _discard(tmp: str) -> None:
        # Cleanup must not mask the original _save error.
        try:
            os.unlink(tmp)
        except OSError:
            pass
