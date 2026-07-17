import pytest
from pydantic import ValidationError
from grokgw.models import ChatCompletionRequest, Message


def test_request_minimal():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="Hello")],
    )
    assert req.model == "grok-4.5"
    assert req.stream is False
    assert req.temperature is None
    assert req.max_tokens is None
    assert req.reasoning_effort is None


def test_request_stream():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="Hi")],
        stream=True,
        reasoning_effort="high",
    )
    assert req.stream is True
    assert req.reasoning_effort == "high"


def test_request_system_user():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ],
    )
    assert len(req.messages) == 2


def test_invalid_reasoning_effort():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="grok-4.5",
            messages=[Message(role="user", content="x")],
            reasoning_effort="invalid",
        )


def test_content_parts_array_coerced_to_string():
    msg = Message(
        role="user",
        content=[{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}],
    )
    assert msg.content == "hello\nworld"


def test_content_null_becomes_empty_string():
    msg = Message(role="assistant", content=None)
    assert msg.content == ""


def test_tool_role_accepted():
    msg = Message(role="tool", content="ok", tool_call_id="call_1")
    assert msg.role == "tool"
    assert msg.tool_call_id == "call_1"
    assert msg.content == "ok"


def test_request_ignores_openai_extra_fields():
    req = ChatCompletionRequest.model_validate(
        {
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "bash", "parameters": {}}}],
            "tool_choice": "auto",
            "stream_options": {"include_usage": True},
        }
    )
    assert req.model == "grok-4.5"
    assert req.messages[0].content == "hi"


def test_request_opencode_style_history():
    req = ChatCompletionRequest.model_validate(
        {
            "model": "grok-4.5",
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": "skill body"}]},
                {
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
                {"role": "tool", "tool_call_id": "c1", "content": "exit 0"},
                {"role": "user", "content": [{"type": "text", "text": "/session-handoff export"}]},
            ],
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "bash", "parameters": {}}}],
        }
    )
    assert req.messages[0].content == "skill body"
    assert req.messages[1].role == "assistant"
    assert req.messages[1].content == ""
    assert req.messages[2].role == "tool"
    assert req.messages[3].content == "/session-handoff export"
