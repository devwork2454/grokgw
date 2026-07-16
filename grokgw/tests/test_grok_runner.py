import asyncio
import json
import pytest
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunner, GrokRunError
from tests.conftest import MockProc


@pytest.fixture
def runner():
    return GrokRunner(Settings())


async def test_run_parses_json_output(monkeypatch, runner):
    json_out = b'{"text":"Hello!","stopReason":"EndTurn","sessionId":"s1","requestId":"q1"}\n'
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    result = await runner.run(["grok", "-p", "Hi", "--output-format", "json"])
    assert result["text"] == "Hello!"
    assert result["stopReason"] == "EndTurn"


async def test_run_stream_yields_events(monkeypatch, runner):
    lines = [
        b'{"type":"text","data":"Hel"}\n',
        b'{"type":"text","data":"lo"}\n',
        b'{"type":"end","stopReason":"EndTurn"}\n',
    ]
    proc = MockProc(stdout_lines=lines, returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    events = []
    async for ev in runner.run_stream(["grok", "-p", "Hi", "--output-format", "streaming-json"]):
        events.append(ev)

    assert len(events) == 3
    assert events[0]["type"] == "text"
    assert events[0]["data"] == "Hel"
    assert events[2]["type"] == "end"


async def test_run_nonzero_exit_raises(monkeypatch, runner):
    proc = MockProc(stdout_lines=[], returncode=1, stderr=b"auth error: please login\n")

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(GrokRunError) as exc_info:
        await runner.run(["grok", "-p", "Hi"])
    assert "auth error" in str(exc_info.value)


async def test_run_timeout_kills_process(monkeypatch, runner):
    import asyncio as aio
    r = GrokRunner(Settings(timeout=1))  # 1 second timeout

    class HangingProc(MockProc):
        async def communicate(self):
            await aio.sleep(100)  # never returns
        async def wait(self):
            await aio.sleep(100)

    proc = HangingProc(stdout_lines=[], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(TimeoutError):
        await r.run(["grok", "-p", "Hi"])
    assert proc._killed is True


async def test_run_injects_proxy_env(monkeypatch):
    """Given proxy_url set, When run(), Then subprocess env has ALL_PROXY/https_proxy."""
    captured: dict = {}
    json_out = b'{"text":"ok","stopReason":"EndTurn"}\n'
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(Settings(proxy_url="socks5h://127.0.0.1:2080"))
    await r.run(["grok", "-p", "Hi"])
    env = captured["env"]
    assert env is not None
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:2080"
    assert env["https_proxy"] == "socks5h://127.0.0.1:2080"
    assert env["HTTPS_PROXY"] == "socks5h://127.0.0.1:2080"


async def test_run_no_proxy_when_disabled(monkeypatch):
    """Given proxy_url=None, When run(), Then env is not overridden for proxy."""
    captured: dict = {}
    json_out = b'{"text":"ok","stopReason":"EndTurn"}\n'
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(Settings(proxy_url=None))
    await r.run(["grok", "-p", "Hi"])
    env = captured["env"]
    if env is not None:
        assert "ALL_PROXY" not in env or env.get("ALL_PROXY") != "socks5h://127.0.0.1:2080"
