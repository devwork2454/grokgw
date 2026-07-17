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
    assert req.tools is None


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


def test_request_accepts_tools_and_tool_messages():
    """OpenAI-style tools + tool role messages must parse (no 422 at model layer)."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[
            Message(role="user", content="read STATUS.md"),
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
            Message(role="tool", content="# status", tool_call_id="call_1"),
        ],
        tools=tools,
        tool_choice="auto",
        parallel_tool_calls=True,
    )
    assert req.tools is not None
    assert req.tools[0]["function"]["name"] == "read_file"
    assert req.messages[1].tool_calls[0]["id"] == "call_1"
    assert req.messages[2].role == "tool"
    assert req.messages[2].tool_call_id == "call_1"
    assert req.tool_choice == "auto"


def test_request_from_raw_dict_like_http_body():
    """Simulate FastAPI body parse of a tools-bearing client request."""
    body = {
        "model": "grok-4.5",
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "a\nb"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "stream": False,
    }
    req = ChatCompletionRequest.model_validate(body)
    assert len(req.messages) == 3
    assert req.tools[0]["function"]["name"] == "bash"
