from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from grokgw.config import Settings
from grokgw.errors import error_body, error_response, format_validation_message
from grokgw.grok_runner import GrokRunError
from grokgw.mapping import unsupported_cli_sampling
from grokgw.media import MediaPathError, resolve_media_file
from grokgw.models import ChatCompletionRequest, ModelInfo, ModelList

_ALLOWED_MODELS = {"grok-4.5", "grok-build", "grok-latest"}
_DEEP_PROBE_TIMEOUT = 5


class RunnerProtocol(Protocol):
    async def complete(self, req: ChatCompletionRequest) -> dict: ...
    def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]: ...


def create_app(
    *,
    runner: RunnerProtocol,
    api_key: str | None,
    max_concurrent: int,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    sem = asyncio.Semaphore(max_concurrent)
    app = FastAPI(title="grokgw")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        msg = format_validation_message(exc.errors())
        return error_response(
            422,
            msg,
            err_type="invalid_request_error",
            code="invalid_request",
        )

    @app.middleware("http")
    async def limit_and_auth_middleware(request: Request, call_next):
        if request.url.path in ("/healthz", "/", "/docs", "/openapi.json"):
            return await call_next(request)

        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > settings.max_body_bytes:
                    return error_response(
                        413,
                        f"request body too large (max {settings.max_body_bytes} bytes)",
                        err_type="invalid_request_error",
                        code="request_too_large",
                    )
            except ValueError:
                pass

        if api_key is not None:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if token != api_key:
                return error_response(
                    401,
                    "invalid API key",
                    err_type="invalid_request_error",
                    code="invalid_api_key",
                )
        return await call_next(request)

    def _check_message_limits(req: ChatCompletionRequest) -> JSONResponse | None:
        if len(req.messages) > settings.max_messages:
            return error_response(
                400,
                f"too many messages ({len(req.messages)} > {settings.max_messages})",
                err_type="invalid_request_error",
                code="context_length_exceeded",
                param="messages",
            )
        total_chars = sum(len(m.content or "") for m in req.messages)
        if total_chars > settings.max_message_chars:
            return error_response(
                400,
                f"messages too large ({total_chars} chars > {settings.max_message_chars})",
                err_type="invalid_request_error",
                code="context_length_exceeded",
                param="messages",
            )
        return None

    async def _deep_checks() -> dict:
        """Backend liveness used by healthz?deep=1."""
        checks: dict = {}
        if settings.backend == "proxy":
            from grokgw.proxy_runner import ProxyRunner

            # Reuse probe logic without mutating a shared runner's cache when possible.
            probe_runner = runner if isinstance(runner, ProxyRunner) else ProxyRunner(settings)
            try:
                if isinstance(probe_runner, ProxyRunner):
                    # Always re-probe for deep health (do not rely on cached route only).
                    proxy = await probe_runner._resolve_proxy()  # noqa: SLF001 — health probe
                    ok = await probe_runner._probe(  # noqa: SLF001
                        settings.upstream_base, proxy_url=proxy
                    )
                else:
                    ok = False
                checks["upstream"] = {
                    "ok": ok,
                    "base": settings.upstream_base,
                    "proxy": proxy if isinstance(probe_runner, ProxyRunner) else None,
                }
            except GrokRunError as e:
                checks["upstream"] = {
                    "ok": False,
                    "base": settings.upstream_base,
                    "error": str(e),
                }
            except Exception as e:  # noqa: BLE001 — health must not raise
                checks["upstream"] = {
                    "ok": False,
                    "base": settings.upstream_base,
                    "error": str(e),
                }
        else:
            which = shutil.which(settings.grok_bin)
            bin_path = which or settings.grok_bin
            exists = bool(which) or (os.path.isfile(bin_path) if os.path.isabs(bin_path) else False)
            checks["grok_binary"] = {
                "ok": exists,
                "path": bin_path,
            }
            if exists:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        settings.grok_bin,
                        "--help",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=_DEEP_PROBE_TIMEOUT)
                        checks["grok_binary"]["help_exit"] = proc.returncode
                        # non-zero still means binary ran
                        checks["grok_binary"]["ok"] = proc.returncode is not None
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                        checks["grok_binary"]["ok"] = False
                        checks["grok_binary"]["error"] = "help timed out"
                except OSError as e:
                    checks["grok_binary"]["ok"] = False
                    checks["grok_binary"]["error"] = str(e)
        return checks

    @app.get("/healthz")
    async def healthz(deep: bool = Query(False, description="Probe upstream or grok binary")):
        body: dict = {
            "status": "ok",
            "backend": settings.backend,
            "upstream_base": settings.upstream_base if settings.backend == "proxy" else None,
            "grok_binary": settings.grok_bin if settings.backend == "cli" else None,
            "grok_cwd": settings.grok_cwd if settings.backend == "cli" else "(sandbox)",
            "proxy_url": settings.proxy_url if settings.backend == "proxy" else None,
            "proxy_mode": settings.proxy_mode if settings.backend == "proxy" else None,
            "media_enabled": settings.media_enabled,
            "sessions_root": settings.sessions_root if settings.media_enabled else None,
            "public_base": settings.public_base if settings.media_enabled else None,
            "max_concurrent": max_concurrent,
            "max_messages": settings.max_messages,
            "max_message_chars": settings.max_message_chars,
            "max_body_bytes": settings.max_body_bytes,
            "cli_serialize": settings.cli_serialize if settings.backend == "cli" else None,
        }
        if deep:
            checks = await _deep_checks()
            body["checks"] = checks
            if any(not c.get("ok", False) for c in checks.values()):
                body["status"] = "degraded"
        return body

    @app.get("/v1/models")
    async def list_models():
        now = int(time.time())
        return ModelList(data=[
            ModelInfo(id="grok-4.5", created=now),
            ModelInfo(id="grok-build", created=now),
            ModelInfo(id="grok-latest", created=now),
        ])

    @app.get("/v1/media/sessions/{session_id}/{kind}/{filename}")
    async def get_media(session_id: str, kind: str, filename: str):
        if not settings.media_enabled:
            return error_response(404, "media disabled", err_type="invalid_request_error", code="media_disabled")
        try:
            path = resolve_media_file(settings.sessions_root, session_id, kind, filename)
        except MediaPathError as e:
            return error_response(404, str(e), err_type="invalid_request_error", code="media_not_found")
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
        }
        mt = media_types.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=mt)

    def _map_runner_error(e: GrokRunError) -> JSONResponse:
        stderr_lower = e.stderr.lower()
        msg = str(e).lower()
        if any(k in stderr_lower or k in msg for k in ("auth", "login", "credential", "unauthorized", "expired")):
            return error_response(
                401,
                "Grok auth expired. Run: grok login",
                err_type="authentication_error",
                code="auth_expired",
            )
        # Prefer status from runner when set to auth-like codes
        status = 502
        if getattr(e, "returncode", None) == 401:
            status = 401
        return error_response(
            status,
            str(e),
            err_type="authentication_error" if status == 401 else "upstream_error",
            code="upstream_error" if status != 401 else "auth_expired",
        )

    def _cli_ignored_headers(req: ChatCompletionRequest) -> dict[str, str]:
        if settings.backend != "cli":
            return {}
        ignored = unsupported_cli_sampling(req)
        if not ignored:
            return {}
        return {"X-Grokgw-Ignored-Params": ",".join(ignored)}

    async def _stream_response(req: ChatCompletionRequest) -> AsyncIterator[str]:
        """Hold the concurrency slot for the entire stream lifetime."""
        async with sem:
            try:
                async for chunk in runner.stream(req):
                    yield chunk
            except GrokRunError as e:
                # Keep OpenAI-ish error object inside SSE for streaming clients.
                yield f"data: {json.dumps(error_body(str(e), err_type='upstream_error', code='upstream_error'))}\n\n"
                yield "data: [DONE]\n\n"
            except TimeoutError as e:
                yield f"data: {json.dumps(error_body(str(e), err_type='timeout_error', code='timeout'))}\n\n"
                yield "data: [DONE]\n\n"

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        if req.model not in _ALLOWED_MODELS:
            return error_response(
                400,
                f"model '{req.model}' not supported. Available: grok-4.5, grok-build, grok-latest",
                err_type="invalid_request_error",
                code="model_not_found",
                param="model",
            )

        limit_err = _check_message_limits(req)
        if limit_err is not None:
            return limit_err

        extra_headers = _cli_ignored_headers(req)

        if req.stream:
            return StreamingResponse(
                _stream_response(req),
                media_type="text/event-stream",
                headers=extra_headers or None,
            )

        async with sem:
            try:
                result = await runner.complete(req)
                if extra_headers:
                    return JSONResponse(content=result, headers=extra_headers)
                return result
            except GrokRunError as e:
                return _map_runner_error(e)
            except TimeoutError as e:
                return error_response(
                    504,
                    str(e),
                    err_type="timeout_error",
                    code="timeout",
                )

    return app
