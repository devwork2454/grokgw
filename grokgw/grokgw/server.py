from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest, ModelInfo, ModelList

_ALLOWED_MODELS = {"grok-4.5", "grok-build", "grok-latest"}


class RunnerProtocol(Protocol):
    async def complete(self, req: ChatCompletionRequest) -> dict: ...
    def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]: ...


def create_app(*, runner: RunnerProtocol, api_key: str | None, max_concurrent: int) -> FastAPI:
    import asyncio

    settings = Settings.from_env()
    sem = asyncio.Semaphore(max_concurrent)
    app = FastAPI(title="grokgw")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path in ("/healthz", "/", "/docs", "/openapi.json"):
            return await call_next(request)
        if api_key is not None:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if token != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"message": "invalid API key", "type": "invalid_request_error"}},
                )
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "backend": settings.backend,
            "upstream_base": settings.upstream_base if settings.backend == "proxy" else None,
            "grok_binary": settings.grok_bin if settings.backend == "cli" else None,
        }

    @app.get("/v1/models")
    async def list_models():
        now = int(time.time())
        return ModelList(data=[
            ModelInfo(id="grok-4.5", created=now),
            ModelInfo(id="grok-build", created=now),
            ModelInfo(id="grok-latest", created=now),
        ])

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        if req.model not in _ALLOWED_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"model '{req.model}' not supported. Available: grok-4.5, grok-build, grok-latest",
            )

        async with sem:
            try:
                if req.stream:
                    return StreamingResponse(
                        _stream_response(runner, req),
                        media_type="text/event-stream",
                    )
                return await runner.complete(req)
            except GrokRunError as e:
                stderr_lower = e.stderr.lower()
                msg = str(e).lower()
                if any(k in stderr_lower or k in msg for k in ("auth", "login", "credential", "unauthorized", "expired")):
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"message": "Grok auth expired. Run: grok login", "type": "authentication_error"}},
                    )
                return JSONResponse(
                    status_code=502,
                    content={"error": {"message": str(e), "type": "upstream_error"}},
                )
            except TimeoutError as e:
                return JSONResponse(
                    status_code=504,
                    content={"error": {"message": str(e), "type": "timeout_error"}},
                )

    async def _stream_response(runner: RunnerProtocol, req: ChatCompletionRequest):
        try:
            async for chunk in runner.stream(req):
                yield chunk
        except GrokRunError as e:
            payload = {
                "error": {"message": str(e), "type": "upstream_error"},
            }
            yield f"data: {__import__('json').dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
        except TimeoutError as e:
            payload = {
                "error": {"message": str(e), "type": "timeout_error"},
            }
            yield f"data: {__import__('json').dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"

    return app
