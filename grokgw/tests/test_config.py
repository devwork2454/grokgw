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


def test_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_PORT", "9999")
    monkeypatch.setenv("GROKGW_MAX_CONCURRENT", "10")
    monkeypatch.setenv("GROKGW_GROK_BIN", "/usr/local/bin/grok")
    monkeypatch.setenv("GROKGW_API_KEY", "secret")
    monkeypatch.setenv("GROKGW_TIMEOUT", "60")
    monkeypatch.setenv("GROKGW_EXPOSE_REASONING", "true")
    s = Settings.from_env()
    assert s.port == 9999
    assert s.max_concurrent == 10
    assert s.grok_bin == "/usr/local/bin/grok"
    assert s.api_key == "secret"
    assert s.timeout == 60
    assert s.expose_reasoning is True
