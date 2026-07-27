from bot.settings import ChatSettings, SettingsStore


def make_store(tmp_path):
    return SettingsStore(tmp_path / "settings.json")


class TestDefaults:
    def test_unknown_chat_gets_defaults(self, tmp_path):
        store = make_store(tmp_path)
        assert store.get(-100123).ban_seconds == 86400


class TestPersistence:
    def test_set_then_get(self, tmp_path):
        store = make_store(tmp_path)
        store.set(-100123, ChatSettings(ban_seconds=3600))
        assert store.get(-100123) == ChatSettings(ban_seconds=3600)

    def test_survives_reload(self, tmp_path):
        path = tmp_path / "settings.json"
        SettingsStore(path).set(-100123, ChatSettings(ban_seconds=3600))
        assert SettingsStore(path).get(-100123) == ChatSettings(ban_seconds=3600)

    def test_chats_are_independent(self, tmp_path):
        store = make_store(tmp_path)
        store.set(-1, ChatSettings(ban_seconds=60))
        assert store.get(-2).ban_seconds == 86400

    def test_creates_parent_dirs(self, tmp_path):
        store = SettingsStore(tmp_path / "nested" / "dir" / "settings.json")
        store.set(-1, ChatSettings(ban_seconds=60))
        assert store.get(-1).ban_seconds == 60

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json")
        store = SettingsStore(path)
        assert store.get(-1).ban_seconds == 86400

    def test_file_with_unknown_fields_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text('{"-1": {"mode": "manual", "ban_seconds": 60}}')
        assert SettingsStore(path).get(-1).ban_seconds == 86400

    def test_bad_entry_does_not_drop_good_ones(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            '{"-1": {"ban_seconds": 3600}, "-2": {"unknown_field": true}}'
        )
        store = SettingsStore(path)
        assert store.get(-1).ban_seconds == 3600
        assert store.get(-2).ban_seconds == 86400

    def test_out_of_range_ban_seconds_ignored(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text('{"-1": {"ban_seconds": 5}}')
        assert SettingsStore(path).get(-1).ban_seconds == 86400

    def test_corrupt_file_backed_up(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json")
        SettingsStore(path)
        assert (tmp_path / "settings.json.bak").read_text() == "{not json"
