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
            if self._killed:
                self._returncode = -9
                return self._returncode
            await aio.sleep(100)
            return 0

    proc = HangingProc(stdout_lines=[], returncode=0)

    async def fake_create(*args, **kwargs):
        assert kwargs.get("start_new_session") is True
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(TimeoutError):
        await r.run(["grok", "-p", "Hi"])
    assert proc._killed is True


async def test_run_stream_timeout_kills_process(monkeypatch):
    import asyncio as aio

    r = GrokRunner(Settings(timeout=1))

    class SlowProc(MockProc):
        @property
        def stdout(self):
            proc = self

            async def _aiter():
                yield b'{"type":"text","data":"x"}\n'
                await aio.sleep(100)
                yield b'{"type":"end","stopReason":"EndTurn"}\n'
                if proc._returncode is None and not proc._killed:
                    proc._returncode = proc._final_returncode

            return _aiter()

        async def wait(self):
            if self._killed:
                self._returncode = -9
                return self._returncode
            await aio.sleep(100)
            return 0

    proc = SlowProc(stdout_lines=[], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(TimeoutError):
        async for _ in r.run_stream(["grok", "-p", "Hi"]):
            pass
    assert proc._killed is True


async def test_run_invalid_json_raises(monkeypatch, runner):
    proc = MockProc(stdout_lines=[b"not-json\n"], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(GrokRunError, match="invalid JSON"):
        await runner.run(["grok", "-p", "Hi"])


async def test_cli_serialize_prevents_concurrent_spawns(monkeypatch):
    import asyncio as aio

    active = 0
    max_active = 0

    class SlowProc(MockProc):
        async def communicate(self):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await aio.sleep(0.05)
            active -= 1
            self._returncode = 0
            return b'{"text":"ok","stopReason":"EndTurn"}\n', b""

    async def fake_create(*args, **kwargs):
        return SlowProc(stdout_lines=[], returncode=0)

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(Settings(cli_serialize=True, media_enabled=False, timeout=5))
    from grokgw.models import ChatCompletionRequest, Message

    req = ChatCompletionRequest(model="grok-4.5", messages=[Message(role="user", content="hi")])
    await aio.gather(r.complete(req), r.complete(req))
    assert max_active == 1


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


async def test_complete_rewrites_media_paths(monkeypatch):
    from grokgw.models import ChatCompletionRequest, Message
    json_out = (
        b'{"text":"Here: images/1.jpg","stopReason":"EndTurn",'
        b'"sessionId":"sess-abc","requestId":"q1"}\n'
    )
    proc = MockProc(stdout_lines=[json_out], returncode=0)
    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(
        Settings(
            media_enabled=True,
            public_base="http://127.0.0.1:8787",
            grok_cwd="/tmp",
            timeout=5,
        )
    )
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="draw")],
    )
    resp = await r.complete(req)
    content = resp["choices"][0]["message"]["content"]
    assert content == "Here: http://127.0.0.1:8787/v1/media/sessions/sess-abc/images/1.jpg"


async def test_complete_no_rewrite_when_media_disabled(monkeypatch):
    from grokgw.models import ChatCompletionRequest, Message
    json_out = (
        b'{"text":"Here: images/1.jpg","stopReason":"EndTurn",'
        b'"sessionId":"sess-abc","requestId":"q1"}\n'
    )
    proc = MockProc(stdout_lines=[json_out], returncode=0)
    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(
        Settings(media_enabled=False, public_base="http://127.0.0.1:8787", grok_cwd="/tmp")
    )
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="draw")],
    )
    resp = await r.complete(req)
    assert resp["choices"][0]["message"]["content"] == "Here: images/1.jpg"
