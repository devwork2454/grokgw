import json
import pytest
from grokgw.config import Settings
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.models import ChatCompletionRequest, Message


def make_req(**kw):
    base = dict(model="grok-4.5", messages=[Message(role="user", content="Hi")])
    base.update(kw)
    return ChatCompletionRequest(**base)


# --- to_cli_args ---

def test_cli_args_single_user_message():
    req = make_req()
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    assert "grok" in args[0] or args[0] == "grok"
    assert "--no-auto-update" in args
    assert "-p" in args
    idx = args.index("-p")
    assert args[idx + 1] == "Hi"
    assert "-m" in args
    assert "grok-4.5" in args
    assert "--cwd" in args
    assert "/tmp/sbx" in args
    assert "--output-format" in args
    assert "json" in args  # non-stream default
    assert "--no-memory" in args
    assert "--always-approve" in args
    assert "--disallowed-tools" not in args  # default: all tools available


def test_cli_args_stream_uses_streaming_json():
    req = make_req(stream=True)
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    of_idx = args.index("--output-format")
    assert args[of_idx + 1] == "streaming-json"


def test_cli_args_multi_message_prompt():
    req = make_req(
        messages=[
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ]
    )
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    p_idx = args.index("-p")
    prompt = args[p_idx + 1]
    assert "system: Be concise." in prompt
    assert "user: Hello" in prompt


def test_cli_args_model_alias_grok_latest():
    req = make_req(model="grok-latest")
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    m_idx = args.index("-m")
    assert args[m_idx + 1] == "grok-4.5"


def test_cli_args_reasoning_effort():
    req = make_req(reasoning_effort="high")
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    re_idx = args.index("--reasoning-effort")
    assert args[re_idx + 1] == "high"


def test_cli_args_grok_bin_from_settings():
    s = Settings(grok_bin="/usr/local/bin/grok")
    req = make_req()
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=s, req_id="r1")
    assert args[0] == "/usr/local/bin/grok"


# --- to_openai_response ---

def test_to_openai_response_endturn():
    data = {"text": "Hello!", "stopReason": "EndTurn", "sessionId": "s1", "requestId": "q1"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "grok-4.5"
    assert resp["choices"][0]["message"]["content"] == "Hello!"
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert resp["id"].startswith("chatcmpl-")


def test_to_openai_response_length():
    data = {"text": "truncated", "stopReason": "Length"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["choices"][0]["finish_reason"] == "length"


def test_to_openai_response_usage_none_when_absent():
    data = {"text": "x", "stopReason": "EndTurn"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["usage"] is None


def test_to_openai_response_usage_passthrough():
    """Given grok json includes usage, When mapped, Then OpenAI usage fields are filled."""
    data = {
        "text": "PONG",
        "stopReason": "EndTurn",
        "usage": {
            "input_tokens": 9972,
            "cache_read_input_tokens": 6016,
            "output_tokens": 36,
            "reasoning_tokens": 30,
            "total_tokens": 16024,
        },
    }
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["usage"] == {
        "prompt_tokens": 9972,
        "completion_tokens": 36,
        "total_tokens": 16024,
    }


# --- to_sse_chunk ---

def test_to_sse_chunk_text():
    ev = {"type": "text", "data": "Hello"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    assert chunk.startswith("data: ")
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["delta"]["content"] == "Hello"
    assert payload["choices"][0]["finish_reason"] is None


def test_to_sse_chunk_end():
    ev = {"type": "end", "stopReason": "EndTurn"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_to_sse_chunk_thought_hidden_by_default():
    ev = {"type": "thought", "data": "thinking..."}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is None  # expose_reasoning=False by default


def test_to_sse_chunk_thought_exposed():
    ev = {"type": "thought", "data": "thinking..."}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings(expose_reasoning=True))
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["delta"]["reasoning_content"] == "thinking..."


def test_to_sse_chunk_error():
    ev = {"type": "error", "message": "boom"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["error"]["message"] == "boom"


def test_to_sse_chunk_unknown_type_skipped():
    ev = {"type": "unknown_future_event", "data": "x"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is None
