from src.config import Settings, load_settings


def test_defaults_are_loopback_on_port_8090():
    settings = Settings()
    assert (settings.host, settings.port) == ("127.0.0.1", 8090)
    assert settings.voice == "en_US-lessac-medium"


def test_exposed_without_token_only_beyond_loopback():
    assert Settings(host="0.0.0.0", internal_token="").exposed_without_token
    assert not Settings(host="0.0.0.0", internal_token="t").exposed_without_token
    assert not Settings(host="127.0.0.1", internal_token="").exposed_without_token


def test_load_settings_reads_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("BARD_PORT", "9123")
    monkeypatch.setenv("BARD_TTL_HOURS", "2")
    monkeypatch.setenv("BARD_QUOTA_MB", "5")
    monkeypatch.setenv("BARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret")
    settings = load_settings()
    assert settings.port == 9123
    assert settings.ttl_seconds == 7200
    assert settings.quota_bytes == 5 * 1024 * 1024
    assert settings.voices_dir == tmp_path / "voices"
    assert settings.audio_dir == tmp_path / "audio"
    assert settings.internal_token == "secret"


def test_admin_settings_default_to_local_ember_api_and_no_static_admins():
    settings = Settings()
    assert settings.ember_api_url == "http://127.0.0.1:8030"
    assert settings.admins == frozenset()
    assert settings.staging_dir.name == "staging"


def test_load_settings_parses_admins_and_the_ember_api_url(monkeypatch, tmp_path):
    monkeypatch.setenv("BARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARD_ADMINS", " Ann, bob ,,")
    monkeypatch.setenv("EMBER_API_URL", "http://ember.lan:8030/")
    settings = load_settings()
    assert settings.admins == frozenset({"ann", "bob"})
    assert settings.ember_api_url == "http://ember.lan:8030"
