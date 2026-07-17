"""OpenAI-compatible error payloads for consistent client handling."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def error_body(
    message: str,
    *,
    err_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"message": message, "type": err_type}
    if code is not None:
        err["code"] = code
    if param is not None:
        err["param"] = param
    return {"error": err}


def error_response(
    status_code: int,
    message: str,
    *,
    err_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(message, err_type=err_type, code=code, param=param),
    )


def format_validation_message(errors: list[dict[str, Any]]) -> str:
    """Turn pydantic/fastapi validation errors into a short client message."""
    parts: list[str] = []
    for err in errors:
        loc = err.get("loc") or ()
        # skip leading "body"
        path = ".".join(str(x) for x in loc if x != "body")
        msg = err.get("msg") or "invalid"
        parts.append(f"{path}: {msg}" if path else str(msg))
    return "; ".join(parts) if parts else "invalid request"
