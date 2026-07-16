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


def test_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_PORT", "9999")
    monkeypatch.setenv("GROKGW_MAX_CONCURRENT", "10")
    monkeypatch.setenv("GROKGW_GROK_BIN", "/usr/local/bin/grok")
    monkeypatch.setenv("GROKGW_API_KEY", "secret")
    monkeypatch.setenv("GROKGW_TIMEOUT", "60")
    monkeypatch.setenv("GROKGW_EXPOSE_REASONING", "true")
    monkeypatch.setenv("GROKGW_PROXY_URL", "socks5h://127.0.0.1:1080")
    monkeypatch.setenv("GROKGW_PROXY_MODE", "always")
    s = Settings.from_env()
    assert s.port == 9999
    assert s.max_concurrent == 10
    assert s.grok_bin == "/usr/local/bin/grok"
    assert s.api_key == "secret"
    assert s.timeout == 60
    assert s.expose_reasoning is True
    assert s.proxy_url == "socks5h://127.0.0.1:1080"
    assert s.proxy_mode == "always"


def test_proxy_url_empty_disables(monkeypatch):
    monkeypatch.setenv("GROKGW_PROXY_URL", "")
    s = Settings.from_env()
    assert s.proxy_url is None


def test_proxy_mode_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("GROKGW_PROXY_MODE", "bogus")
    s = Settings.from_env()
    assert s.proxy_mode == "auto"
