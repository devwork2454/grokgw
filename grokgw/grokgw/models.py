from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """OpenAI-compatible chat message (proxy pass-through for tool fields)."""

    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Any = None  # str | list | null (tool/assistant tool_calls)
    name: str | None = None
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None
    function_call: Any | None = None  # legacy OpenAI


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completions request."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[Message]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    # native function calling (OpenAI-compatible)
    tools: list[Any] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
    # legacy function calling
    functions: list[Any] | None = None
    function_call: Any | None = None
    # common optional knobs forwarded by proxy
    response_format: Any | None = None
    stop: Any | None = None
    user: str | None = None
    n: int | None = None


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[Any] | None = None
    function_call: Any | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None


class Delta(BaseModel):
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[Any] | None = None
    function_call: Any | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]


class ModelInfo(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str = "xai"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelInfo]
