import os

from grokgw.config import Settings


def test_defaults():
    s = Settings()
    assert s.port == 8787
    assert s.max_concurrent == 3
    assert s.sandbox_root == "/tmp"
    assert s.api_key is None
    assert s.grok_bin == "grok"
    assert s.timeout == 120
    assert s.expose_reasoning is False
    assert s.proxy_url == "socks5h://127.0.0.1:2080"
    assert s.proxy_mode == "auto"
    assert s.backend == "proxy"
    assert s.max_messages == 200
    assert s.max_message_chars == 500_000
    assert s.max_body_bytes == 2_000_000
    assert s.cli_serialize is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_PORT", "9999")
    monkeypatch.setenv("GROKGW_MAX_CONCURRENT", "10")
    monkeypatch.setenv("GROKGW_GROK_BIN", "/usr/local/bin/grok")
    monkeypatch.setenv("GROKGW_API_KEY", "secret")
    monkeypatch.setenv("GROKGW_TIMEOUT", "60")
    monkeypatch.setenv("GROKGW_EXPOSE_REASONING", "true")
    monkeypatch.setenv("GROKGW_PROXY_URL", "socks5h://127.0.0.1:1080")
    monkeypatch.setenv("GROKGW_PROXY_MODE", "always")
    monkeypatch.setenv("GROKGW_MAX_MESSAGES", "50")
    monkeypatch.setenv("GROKGW_CLI_SERIALIZE", "0")
    s = Settings.from_env()
    assert s.port == 9999
    assert s.max_concurrent == 10
    assert s.grok_bin == "/usr/local/bin/grok"
    assert s.api_key == "secret"
    assert s.timeout == 60
    assert s.expose_reasoning is True
    assert s.proxy_url == "socks5h://127.0.0.1:1080"
    assert s.proxy_mode == "always"
    assert s.max_messages == 50
    assert s.cli_serialize is False


def test_cli_backend_defaults_max_concurrent_one(monkeypatch):
    monkeypatch.setenv("GROKGW_BACKEND", "cli")
    monkeypatch.delenv("GROKGW_MAX_CONCURRENT", raising=False)
    s = Settings.from_env()
    assert s.backend == "cli"
    assert s.max_concurrent == 1


def test_proxy_url_empty_disables(monkeypatch):
    monkeypatch.setenv("GROKGW_PROXY_URL", "")
    s = Settings.from_env()
    assert s.proxy_url is None


def test_proxy_mode_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("GROKGW_PROXY_MODE", "bogus")
    s = Settings.from_env()
    assert s.proxy_mode == "auto"


def test_media_defaults():
    s = Settings()
    assert s.media_enabled is True
    assert s.sessions_root == os.path.expanduser("~/.grok/sessions")
    assert s.public_base == "http://127.0.0.1:8787"


def test_media_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_MEDIA", "0")
    monkeypatch.setenv("GROKGW_SESSIONS_ROOT", "/tmp/fake-sessions")
    monkeypatch.setenv("GROKGW_PUBLIC_BASE", "http://example.local:9000")
    monkeypatch.setenv("GROKGW_HOST", "0.0.0.0")
    monkeypatch.setenv("GROKGW_PORT", "9000")
    s = Settings.from_env()
    assert s.media_enabled is False
    assert s.sessions_root == "/tmp/fake-sessions"
    assert s.public_base == "http://example.local:9000"


def test_media_enabled_timeout_default_when_unset(monkeypatch):
    monkeypatch.delenv("GROKGW_TIMEOUT", raising=False)
    monkeypatch.setenv("GROKGW_MEDIA", "1")
    s = Settings.from_env()
    assert s.media_enabled is True
    assert s.timeout == 300


def test_explicit_timeout_wins(monkeypatch):
    monkeypatch.setenv("GROKGW_MEDIA", "1")
    monkeypatch.setenv("GROKGW_TIMEOUT", "90")
    s = Settings.from_env()
    assert s.timeout == 90

