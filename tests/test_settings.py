from bot.settings import ChatSettings, SettingsStore


def make_store(tmp_path):
    return SettingsStore(tmp_path / "settings.json")


class TestDefaults:
    def test_unknown_chat_gets_defaults(self, tmp_path):
        store = make_store(tmp_path)
        settings = store.get(-100123)
        assert settings.mode == "manual"
        assert settings.ban_seconds == 86400


class TestPersistence:
    def test_set_then_get(self, tmp_path):
        store = make_store(tmp_path)
        store.set(-100123, ChatSettings(mode="auto", ban_seconds=3600))
        assert store.get(-100123) == ChatSettings(mode="auto", ban_seconds=3600)

    def test_survives_reload(self, tmp_path):
        path = tmp_path / "settings.json"
        SettingsStore(path).set(-100123, ChatSettings(mode="auto", ban_seconds=3600))
        assert SettingsStore(path).get(-100123) == ChatSettings(
            mode="auto", ban_seconds=3600
        )

    def test_chats_are_independent(self, tmp_path):
        store = make_store(tmp_path)
        store.set(-1, ChatSettings(mode="auto", ban_seconds=60))
        assert store.get(-2).mode == "manual"

    def test_creates_parent_dirs(self, tmp_path):
        store = SettingsStore(tmp_path / "nested" / "dir" / "settings.json")
        store.set(-1, ChatSettings(mode="auto", ban_seconds=60))
        assert store.get(-1).mode == "auto"

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json")
        store = SettingsStore(path)
        assert store.get(-1).mode == "manual"
