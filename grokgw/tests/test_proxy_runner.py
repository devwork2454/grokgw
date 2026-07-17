import asyncio
import json

import pytest

from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest, Message
from grokgw.proxy_runner import (
    ProxyRunner,
    build_upstream_payload,
    _strip_reasoning_complete,
    _strip_reasoning_sse_data,
)
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
    defaults = dict(
        backend="proxy",
        upstream_base="https://api.x.ai/v1",
        auth_path=str(p),
        proxy_url="socks5h://127.0.0.1:2080",
        proxy_mode="auto",
        timeout=30,
        expose_reasoning=False,
    )
    defaults.update(kw)
    return Settings(**defaults)


async def test_complete_parses_response(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always")
    json_out = json.dumps(
        {"id": "1", "choices": [{"message": {"content": "PONG"}}], "usage": {"total_tokens": 12}}
    ).encode()
    proc = MockProc(stdout_lines=[json_out + b"\n"], returncode=0)

    async def fake(*a, **kw):
        return proc

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
        return MockProc(stdout_lines=[b"{}"], returncode=0)

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    await ProxyRunner(s).complete(_req())
    assert "-x" not in captured


async def test_auto_probes_direct_first(monkeypatch, tmp_path):
    """auto mode: when direct probe succeeds, real request omits -x."""
    s = _settings(tmp_path, proxy_mode="auto", proxy_url="socks5h://127.0.0.1:2080")
    captured_cmds: list[list] = []

    async def fake_create(*args, **kw):
        captured_cmds.append(list(args))
        # probe uses -w %{http_code}; complete uses chat/completions
        joined = " ".join(str(a) for a in args)
        if "%{http_code}" in joined or "/models" in joined:
            return MockProc(stdout_lines=[b"200"], returncode=0)
        body = json.dumps({"choices": [{"message": {"content": "PONG"}}]}).encode() + b"\n"
        return MockProc(stdout_lines=[body], returncode=0)

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["content"] == "PONG"
    # last call is the chat request — must not use -x when direct works
    chat_cmd = captured_cmds[-1]
    assert "chat/completions" in " ".join(str(a) for a in chat_cmd)
    assert "-x" not in chat_cmd


def test_strip_reasoning_sse_drops_pure_reasoning():
    """Shipped helper: pure reasoning deltas are dropped."""
    payload = json.dumps({"choices": [{"delta": {"reasoning_content": "think"}}]})
    assert _strip_reasoning_sse_data(payload) is None


def test_strip_reasoning_sse_keeps_content():
    payload = json.dumps({"choices": [{"delta": {"content": "Hi"}}]})
    out = json.loads(_strip_reasoning_sse_data(payload))
    assert out["choices"][0]["delta"]["content"] == "Hi"
    assert "reasoning_content" not in out["choices"][0]["delta"]


def test_strip_reasoning_sse_keeps_role_strips_reasoning():
    payload = json.dumps(
        {"choices": [{"delta": {"role": "assistant", "reasoning_content": "x"}}]}
    )
    out = json.loads(_strip_reasoning_sse_data(payload))
    assert out["choices"][0]["delta"] == {"role": "assistant"}


def test_strip_reasoning_complete_removes_message_field():
    data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "OK",
                    "reasoning_content": "secret",
                }
            }
        ]
    }
    out = _strip_reasoning_complete(data)
    assert out["choices"][0]["message"]["content"] == "OK"
    assert "reasoning_content" not in out["choices"][0]["message"]


async def test_stream_emits_single_done_and_drops_reasoning(monkeypatch, tmp_path):
    """ProxyRunner.stream: at most one [DONE]; no reasoning when expose_reasoning=false."""
    s = _settings(tmp_path, proxy_mode="never", expose_reasoning=False)
    lines = [
        b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n',
        b'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"x"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b"data: [DONE]\n",
        b"data: [DONE]\n",  # double upstream DONE must still become one
    ]
    proc = MockProc(stdout_lines=lines, returncode=0)

    async def fake(*a, **kw):
        return proc

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake)
    frames: list[str] = []
    async for chunk in ProxyRunner(s).stream(_req()):
        frames.append(chunk)
    joined = "".join(frames)
    assert joined.count("[DONE]") == 1, joined
    assert "reasoning_content" not in joined
    assert "Hello" in joined
    # last non-empty frame is DONE
    nonempty = [f for f in frames if f.strip()]
    assert nonempty[-1].strip().startswith("data: [DONE]")


async def test_complete_strips_reasoning_when_disabled(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never", expose_reasoning=False)
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "pong",
                    "reasoning_content": "hidden",
                }
            }
        ]
    }
    proc = MockProc(stdout_lines=[json.dumps(body).encode() + b"\n"], returncode=0)

    async def fake(*a, **kw):
        return proc

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["content"] == "pong"
    assert "reasoning_content" not in out["choices"][0]["message"]


async def test_complete_keeps_reasoning_when_enabled(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never", expose_reasoning=True)
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "pong",
                    "reasoning_content": "visible",
                }
            }
        ]
    }
    proc = MockProc(stdout_lines=[json.dumps(body).encode() + b"\n"], returncode=0)

    async def fake(*a, **kw):
        return proc

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["reasoning_content"] == "visible"


def test_build_upstream_payload_plain_chat():
    """Plain chat payload stays minimal (no tools keys)."""
    payload = build_upstream_payload(_req(), stream=False)
    assert payload["model"] == "grok-4.5"
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "Hi"}]
    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_build_upstream_payload_forwards_tools_and_tool_messages():
    """Tools + multi-turn tool messages must appear on the upstream wire payload."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]
    req = ChatCompletionRequest(
        model="grok-latest",
        messages=[
            Message(role="user", content="read it"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"docs/STATUS.md"}',
                        },
                    }
                ],
            ),
            Message(role="tool", content="ok", tool_call_id="call_1"),
        ],
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
        max_tokens=128,
    )
    payload = build_upstream_payload(req, stream=True)
    assert payload["model"] == "grok-4.5"  # alias
    assert payload["stream"] is True
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 128
    assert payload["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert payload["messages"][1].get("content") is None
    assert payload["messages"][2] == {
        "role": "tool",
        "content": "ok",
        "tool_call_id": "call_1",
    }


async def test_complete_curl_includes_tools_json(monkeypatch, tmp_path):
    """ProxyRunner.complete must put tools into the curl -d body (shipped path)."""
    s = _settings(tmp_path, proxy_mode="never")
    captured: list = []
    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    body = {
        "id": "1",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    async def fake_create(*args, **kw):
        captured.extend(args)
        return MockProc(stdout_lines=[json.dumps(body).encode() + b"\n"], returncode=0)

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake_create)
    out = await ProxyRunner(s).complete(
        _req(tools=tools, tool_choice="auto")
    )
    # find JSON -d argument
    assert "-d" in captured
    di = list(captured).index("-d")
    wire = json.loads(captured[di + 1])
    assert wire["tools"] == tools
    assert wire["tool_choice"] == "auto"
    assert wire["messages"][0]["content"] == "Hi"
    # response tool_calls preserved (and reasoning strip does not drop them)
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "c1"
    assert out["choices"][0]["finish_reason"] == "tool_calls"


def test_strip_reasoning_sse_keeps_tool_calls_delta():
    """Reasoning filter must not drop pure tool_calls deltas."""
    payload = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "bash", "arguments": ""},
                            }
                        ]
                    }
                }
            ]
        }
    )
    out = _strip_reasoning_sse_data(payload)
    assert out is not None
    parsed = json.loads(out)
    assert parsed["choices"][0]["delta"]["tool_calls"][0]["id"] == "c1"


def test_strip_reasoning_sse_keeps_tool_calls_finish():
    payload = json.dumps(
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    )
    out = _strip_reasoning_sse_data(payload)
    assert out is not None
    assert json.loads(out)["choices"][0]["finish_reason"] == "tool_calls"


def test_strip_reasoning_complete_keeps_tool_calls_on_message():
    data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "plan",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    out = _strip_reasoning_complete(data)
    msg = out["choices"][0]["message"]
    assert "reasoning_content" not in msg
    assert msg["tool_calls"][0]["id"] == "c1"


async def test_stream_forwards_tool_calls_and_single_done(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never", expose_reasoning=False)
    lines = [
        b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n',
        (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            b'"type":"function","function":{"name":"bash","arguments":"{}"}}]}}]}\n'
        ),
        b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n',
        b"data: [DONE]\n",
    ]
    proc = MockProc(stdout_lines=lines, returncode=0)

    async def fake(*a, **kw):
        return proc

    monkeypatch.setattr("grokgw.proxy_runner.asyncio.create_subprocess_exec", fake)
    frames: list[str] = []
    async for chunk in ProxyRunner(s).stream(_req(tools=[{"type": "function"}])):
        frames.append(chunk)
    joined = "".join(frames)
    assert joined.count("[DONE]") == 1
    assert "reasoning_content" not in joined
    assert "tool_calls" in joined
    assert "bash" in joined
    assert "tool_calls" in joined  # finish reason also present
