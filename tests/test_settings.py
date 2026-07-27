import pytest

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
        assert store.set(-100123, ChatSettings(ban_seconds=3600)) is True
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

    @pytest.mark.parametrize("value", ["3600.5", "true", '"3600"'])
    def test_non_int_ban_seconds_ignored(self, tmp_path, value):
        path = tmp_path / "settings.json"
        path.write_text('{"-1": {"ban_seconds": %s}}' % value)
        assert SettingsStore(path).get(-1).ban_seconds == 86400

    def test_stale_tmp_files_cleaned_on_start(self, tmp_path):
        stale = tmp_path / "settings-abc123.tmp"
        stale.write_text("{}")
        make_store(tmp_path)
        assert not stale.exists()

    def test_foreign_tmp_files_untouched(self, tmp_path):
        foreign = tmp_path / "tmpother.tmp"
        foreign.write_text("{}")
        make_store(tmp_path)
        assert foreign.exists()

    def test_save_failure_keeps_memory_and_does_not_raise(self, tmp_path):
        store = make_store(tmp_path)
        tmp_path.chmod(0o500)
        try:
            assert store.set(-1, ChatSettings(ban_seconds=3600)) is False
            assert store.get(-1).ban_seconds == 3600
        finally:
            tmp_path.chmod(0o700)

    def test_save_failure_not_masked_by_cleanup_failure(self, tmp_path, monkeypatch):
        import bot.settings as settings_module

        store = make_store(tmp_path)

        def fail_replace(*args):
            raise PermissionError("disk full")

        def fail_unlink(*args):
            raise OSError("cleanup failed")

        monkeypatch.setattr(settings_module.os, "replace", fail_replace)
        monkeypatch.setattr(settings_module.os, "unlink", fail_unlink)
        store._settings[-1] = ChatSettings(ban_seconds=3600)
        with pytest.raises(PermissionError, match="disk full"):
            store._save()

    def test_corrupt_file_backed_up(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json")
        SettingsStore(path)
        assert (tmp_path / "settings.json.bak").read_text() == "{not json"
