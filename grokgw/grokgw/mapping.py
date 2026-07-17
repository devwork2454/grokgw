from __future__ import annotations
import json
import time
import uuid
from grokgw.config import Settings
from grokgw.models import ChatCompletionRequest

_MODEL_ALIASES = {"grok-latest": "grok-4.5"}
_FINISH_MAP = {"endturn": "stop", "toolcalls": "tool_calls", "length": "length"}


def _format_message_line(role: str, content: str, *, tool_call_id: str | None = None) -> str:
    body = content if content else ""
    if role in ("tool", "function") and tool_call_id:
        return f"{role}[{tool_call_id}]: {body}".rstrip()
    return f"{role}: {body}".rstrip()


def _build_prompt(req: ChatCompletionRequest) -> str:
    if len(req.messages) == 1 and req.messages[0].role == "user":
        return req.messages[0].content
    lines: list[str] = []
    for m in req.messages:
        # Skip empty assistant tool-call placeholders with no text.
        if m.role == "assistant" and not m.content and m.tool_calls:
            names = []
            for tc in m.tool_calls:
                if isinstance(tc, dict):
                    fn = (tc.get("function") or {}).get("name")
                    if fn:
                        names.append(str(fn))
            label = ", ".join(names) if names else "tool"
            lines.append(f"assistant: [calling {label}]")
            continue
        if not m.content and m.role != "user":
            continue
        lines.append(
            _format_message_line(m.role, m.content, tool_call_id=m.tool_call_id)
        )
    return "\n".join(lines) if lines else ""


def to_upstream_messages(req: ChatCompletionRequest) -> list[dict[str, str]]:
    """Normalize messages for OpenAI-compatible upstream (proxy backend).

    Upstream xAI chat typically wants system/user/assistant with string content.
    Tool / function rows are folded into user-visible text so OpenCode history
    does not 422 at the gateway and still reaches the model as context.
    """
    out: list[dict[str, str]] = []
    for m in req.messages:
        if m.role in ("tool", "function"):
            tid = f" ({m.tool_call_id})" if m.tool_call_id else ""
            text = m.content or ""
            out.append({"role": "user", "content": f"[tool result{tid}]: {text}".rstrip()})
            continue
        if m.role == "assistant" and not m.content and m.tool_calls:
            names = []
            for tc in m.tool_calls:
                if isinstance(tc, dict):
                    fn = (tc.get("function") or {}).get("name")
                    if fn:
                        names.append(str(fn))
            label = ", ".join(names) if names else "tool"
            out.append({"role": "assistant", "content": f"[calling {label}]"})
            continue
        if m.role in ("system", "user", "assistant"):
            out.append({"role": m.role, "content": m.content or ""})
    if not out:
        out.append({"role": "user", "content": ""})
    return out


def resolve_model_id(model: str) -> str:
    return _MODEL_ALIASES.get(model, model)


def sampling_kwargs(req: ChatCompletionRequest) -> dict:
    """Sampling fields supported by OpenAI-compatible upstream APIs."""
    out: dict = {}
    if req.temperature is not None:
        out["temperature"] = req.temperature
    if req.max_tokens is not None:
        out["max_tokens"] = req.max_tokens
    if req.top_p is not None:
        out["top_p"] = req.top_p
    if req.reasoning_effort is not None:
        out["reasoning_effort"] = req.reasoning_effort
    return out


def unsupported_cli_sampling(req: ChatCompletionRequest) -> list[str]:
    """Params accepted by the gateway but not applied on the CLI backend."""
    ignored: list[str] = []
    if req.temperature is not None:
        ignored.append("temperature")
    if req.max_tokens is not None:
        ignored.append("max_tokens")
    if req.top_p is not None:
        ignored.append("top_p")
    return ignored


def to_upstream_chat_payload(req: ChatCompletionRequest, *, stream: bool) -> dict:
    """Full chat.completions JSON body for the proxy backend."""
    payload: dict = {
        "model": resolve_model_id(req.model),
        "messages": to_upstream_messages(req),
        "stream": stream,
    }
    payload.update(sampling_kwargs(req))
    return payload


def to_cli_args(
    req: ChatCompletionRequest, *, sandbox_dir: str, settings: Settings, req_id: str
) -> list[str]:
    prompt = _build_prompt(req)
    model = resolve_model_id(req.model)
    args = [
        settings.grok_bin,
        "--no-auto-update",
        "-p", prompt,
        "-m", model,
        "--cwd", sandbox_dir,
        "--output-format", "streaming-json" if req.stream else "json",
        "--no-memory",
        "--always-approve",
    ]
    if settings.grok_tools:
        args += ["--tools", settings.grok_tools]
    if settings.grok_disallowed_tools:
        args += ["--disallowed-tools", settings.grok_disallowed_tools]
    if req.reasoning_effort:
        args += ["--reasoning-effort", req.reasoning_effort]
    # temperature / max_tokens / top_p: not supported by grok CLI flags
    return args


def _map_usage(raw: dict | None) -> dict | None:
    if not raw or not isinstance(raw, dict):
        return None
    prompt = raw.get("input_tokens")
    completion = raw.get("output_tokens")
    total = raw.get("total_tokens")
    if prompt is None and completion is None and total is None:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def to_openai_response(data: dict, req: ChatCompletionRequest) -> dict:
    stop_raw = data.get("stopReason", "EndTurn")
    finish = _FINISH_MAP.get(stop_raw.lower(), "stop")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": data.get("text", "")},
            "finish_reason": finish,
        }],
        "usage": _map_usage(data.get("usage")),
    }


def to_sse_chunk(event: dict, *, req_id: str, model: str, settings: Settings) -> str | None:
    etype = event.get("type")

    if etype == "text":
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": event.get("data", "")}, "finish_reason": None}],
        }
    elif etype == "thought" and settings.expose_reasoning:
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"reasoning_content": event.get("data", "")}, "finish_reason": None}],
        }
    elif etype == "end":
        stop_raw = event.get("stopReason", "EndTurn")
        finish = _FINISH_MAP.get(stop_raw.lower(), "stop")
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
        }
    elif etype == "error":
        payload = {
            "error": {"message": event.get("message", "grok error"), "type": "upstream_error"},
        }
    else:
        return None

    return f"data: {json.dumps(payload)}\n\n"
