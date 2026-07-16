from __future__ import annotations
import time
import uuid
from collections.abc import AsyncIterator
from typing import Protocol
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.models import ChatCompletionRequest, ModelInfo, ModelList
from grokgw.sandbox import create as create_sandbox, cleanup as cleanup_sandbox

_ALLOWED_MODELS = {"grok-4.5", "grok-build", "grok-latest"}


class RunnerProtocol(Protocol):
    async def run(self, args: list[str]) -> dict: ...
    def run_stream(self, args: list[str]) -> AsyncIterator[dict]: ...


def create_app(*, runner: RunnerProtocol, api_key: str | None, max_concurrent: int) -> FastAPI:
    import asyncio
    settings = Settings.from_env()
    sem = asyncio.Semaphore(max_concurrent)

    app = FastAPI(title="grokgw")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # healthz and docs bypass auth (liveness/readiness)
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
        return {"status": "ok", "grok_binary": settings.grok_bin}

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
            sandbox_dir = create_sandbox(root=settings.sandbox_root)
            req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            args = to_cli_args(req, sandbox_dir=sandbox_dir, settings=settings, req_id=req_id)
            try:
                if req.stream:
                    return StreamingResponse(
                        _stream_response(runner, args, req_id, req.model, settings, sandbox_dir),
                        media_type="text/event-stream",
                    )
                else:
                    data = await runner.run(args)
                    return to_openai_response(data, req)
            except GrokRunError as e:
                stderr_lower = e.stderr.lower()
                if "auth" in stderr_lower or "login" in stderr_lower or "credential" in stderr_lower:
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
            finally:
                if not req.stream:
                    cleanup_sandbox(sandbox_dir)

    async def _stream_response(runner, args, req_id, model, settings, sandbox_dir):
        try:
            async for event in runner.run_stream(args):
                chunk = to_sse_chunk(event, req_id=req_id, model=model, settings=settings)
                if chunk is not None:
                    yield chunk
            yield "data: [DONE]\n\n"
        except GrokRunError as e:
            err_chunk = to_sse_chunk(
                {"type": "error", "message": str(e)},
                req_id=req_id,
                model=model,
                settings=settings,
            )
            if err_chunk is not None:
                yield err_chunk
            yield "data: [DONE]\n\n"
        except TimeoutError as e:
            err_chunk = to_sse_chunk(
                {"type": "error", "message": str(e)},
                req_id=req_id,
                model=model,
                settings=settings,
            )
            if err_chunk is not None:
                yield err_chunk
            yield "data: [DONE]\n\n"
        finally:
            cleanup_sandbox(sandbox_dir)

    return app
