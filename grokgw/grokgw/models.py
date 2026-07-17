from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


def coerce_message_content(value: Any) -> str:
    """Normalize OpenAI/OpenCode content into a plain string.

    Accepts str, None, or a list of content parts
    (e.g. ``[{"type":"text","text":"..."}]``).
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "text" or "text" in item:
                text = item.get("text")
                if text is not None and str(text):
                    parts.append(str(text))
            elif typ == "image_url":
                parts.append("[image]")
            elif typ == "input_image":
                parts.append("[image]")
            elif typ == "refusal":
                refusal = item.get("refusal")
                if refusal:
                    parts.append(str(refusal))
        return "\n".join(parts)
    return str(value)


class Message(BaseModel):
    """Chat message compatible with OpenAI agents / OpenCode payloads."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool", "function"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[Any] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, value: Any) -> str:
        return coerce_message_content(value)


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat request; unknown fields (tools, etc.) are ignored."""

    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[Message]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


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
