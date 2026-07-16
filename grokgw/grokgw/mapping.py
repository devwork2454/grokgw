from __future__ import annotations
import json
import time
import uuid
from grokgw.config import Settings
from grokgw.models import ChatCompletionRequest

_MODEL_ALIASES = {"grok-latest": "grok-4.5"}
_FINISH_MAP = {"endturn": "stop", "toolcalls": "tool_calls", "length": "length"}


def _build_prompt(req: ChatCompletionRequest) -> str:
    if len(req.messages) == 1 and req.messages[0].role == "user":
        return req.messages[0].content
    return "\n".join(f"{m.role}: {m.content}" for m in req.messages)


def to_cli_args(
    req: ChatCompletionRequest, *, sandbox_dir: str, settings: Settings, req_id: str
) -> list[str]:
    prompt = _build_prompt(req)
    model = _MODEL_ALIASES.get(req.model, req.model)
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
