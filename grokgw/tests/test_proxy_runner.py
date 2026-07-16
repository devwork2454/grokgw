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


@pytest.fixture
def settings(tmp_path):
    auth = {
        "https://auth.x.ai::c": {
            "key": "tok",
            "refresh_token": "ref",
            "expires_at": "2099-01-01T00:00:00.000Z",
            "oidc_issuer": "https://auth.x.ai",
            "oidc_client_id": "c",
        }
    }
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps(auth))
    return Settings(
        backend="proxy",
        upstream_base="https://api.x.ai/v1",
        auth_path=str(auth_path),
        proxy_url="socks5h://127.0.0.1:2080",
        timeout=30,
    )


async def test_complete_parses_response(monkeypatch, settings):
    json_out = json.dumps({
        "id": "chatcmpl-1", "object": "chat.completion", "model": "grok-4.5",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "PONG"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }).encode()
    proc = MockProc(stdout_lines=[json_out + b"\n"], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)

    runner = ProxyRunner(settings)
    out = await runner.complete(_req())
    assert out["choices"][0]["message"]["content"] == "PONG"
    assert out["usage"]["total_tokens"] == 12


async def test_complete_upstream_error_json(monkeypatch, settings):
    err = json.dumps({"error": {"message": "unauthorized", "code": 401}}).encode()
    proc = MockProc(stdout_lines=[err + b"\n"], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)

    runner = ProxyRunner(settings)
    with pytest.raises(GrokRunError, match="unauthorized"):
        await runner.complete(_req())


async def test_stream_yields_sse_lines(monkeypatch, settings):
    lines = [
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n',
        b"data: [DONE]\n",
    ]
    proc = MockProc(stdout_lines=lines, returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)

    runner = ProxyRunner(settings)
    chunks = [ln async for ln in runner.stream(_req(stream=True))]
    assert any("Hi" in ln for ln in chunks)
    assert any("[DONE]" in ln for ln in chunks)
