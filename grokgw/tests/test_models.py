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
