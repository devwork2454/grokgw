import json

import pytest

from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest, Message
from grokgw.proxy_runner import ProxyRunner
from tests.conftest import MockProc


def _req(**kw) -> ChatCompletionRequest:
    base = dict(model="grok-4.5", messages=[Message(role="user", content="Hi")])
    base.update(kw)
    return ChatCompletionRequest(**base)


def _settings(tmp_path, **kw) -> Settings:
    auth = {
        "https://auth.x.ai::c": {
            "key": "tok", "refresh_token": "ref",
            "expires_at": "2099-01-01T00:00:00.000Z",
            "oidc_issuer": "https://auth.x.ai", "oidc_client_id": "c",
        }
    }
    p = tmp_path / "auth.json"
    p.write_text(json.dumps(auth))
    defaults = dict(backend="proxy", upstream_base="https://api.x.ai/v1",
                    auth_path=str(p), proxy_url="socks5h://127.0.0.1:2080",
                    proxy_mode="auto", timeout=30)
    defaults.update(kw)
    return Settings(**defaults)


async def test_complete_parses_response(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always")
    json_out = json.dumps({"id":"1","choices":[{"message":{"content":"PONG"}}],"usage":{"total_tokens":12}}).encode()
    proc = MockProc(stdout_lines=[json_out + b"\n"], returncode=0)
    async def fake(*a, **kw): return proc
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["content"] == "PONG"


async def test_always_uses_proxy(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always", proxy_url="socks5h://1.2.3.4:1080")
    captured: list = []
    async def fake_create(*args, **kw):
        captured.extend(args)
        return MockProc(stdout_lines=[b'{"error":{"message":"auth"}}\n'], returncode=0)
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    with pytest.raises(GrokRunError, match="auth"):
        await ProxyRunner(s).complete(_req())
    assert "-x" in captured
    assert "socks5h://1.2.3.4:1080" in captured


async def test_never_uses_no_proxy(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never")
    captured: list = []
    async def fake_create(*args, **kw):
        captured.extend(args)
        return MockProc(stdout_lines=[b'{}'], returncode=0)
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    await ProxyRunner(s).complete(_req())
    assert "-x" not in captured


async def test_auto_probes_direct_first(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="auto", proxy_url="socks5h://127.0.0.1:2080")
    probe_results = [b"200\n"]  # direct probe succeeds
    call_count = 0

    async def fake_create(*args, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # probe call
            return MockProc(stdout_lines=probe_results, returncode=0)
        else:  # real call
            json_out = json.dumps({"choices":[{"message":{"content":"PONG"}}]}).encode()
            return MockProc(stdout_lines=[json_out + b"\n"], returncode=0)

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    runner = ProxyRunner(s)
    runner._probe = lambda url, proxy_url: asyncio.coroutine(lambda: True)()
    # simpler: just monkeypatch _probe directly
