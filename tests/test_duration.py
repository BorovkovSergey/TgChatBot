import pytest

from bot.settings import DurationError, format_duration, parse_duration


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("60s", 60),
            ("45m", 45 * 60),
            ("2h", 2 * 3600),
            ("3d", 3 * 86400),
            ("365d", 365 * 86400),
            ("1D", 86400),
            (" 2h ", 2 * 3600),
        ],
    )
    def test_valid(self, text, expected):
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["", "abc", "10", "h", "-5m", "1.5h", "10w"])
    def test_invalid_format(self, text):
        with pytest.raises(DurationError):
            parse_duration(text)

    def test_below_minimum(self):
        # 60s floor: Telegram turns sub-30s bans into permanent ones, and
        # latency/clock skew can eat the margin near the boundary
        with pytest.raises(DurationError):
            parse_duration("59s")

    def test_above_maximum(self):
        # 365d ceiling: Telegram's limit is 366d, clock skew past it would
        # make the ban permanent
        with pytest.raises(DurationError):
            parse_duration("366d")


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (30, "30s"),
            (45 * 60, "45m"),
            (2 * 3600, "2h"),
            (86400, "1d"),
            (3 * 86400, "3d"),
            (90 * 60, "1h 30m"),
            (86400 + 3600, "1d 1h"),
            (0, "0s"),
        ],
    )
    def test_format(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_roundtrip(self):
        assert parse_duration(format_duration(7200)) == 7200
