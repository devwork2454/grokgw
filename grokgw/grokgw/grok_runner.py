from __future__ import annotations
import asyncio
import json
import os
from collections.abc import AsyncIterator

from grokgw.config import Settings
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.models import ChatCompletionRequest
from grokgw.sandbox import cleanup as cleanup_sandbox
from grokgw.sandbox import create as create_sandbox

_KILL_GRACE = 2


class GrokRunError(Exception):
    def __init__(self, message: str, returncode: int, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class GrokRunner:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def complete(self, req: ChatCompletionRequest) -> dict:
        sandbox_dir = self._resolve_cwd()
        try:
            args = to_cli_args(
                req.model_copy(update={"stream": False}),
                sandbox_dir=sandbox_dir,
                settings=self._settings,
                req_id="cli",
            )
            data = await self.run(args)
            return to_openai_response(data, req)
        finally:
            if sandbox_dir != self._settings.grok_cwd:
                cleanup_sandbox(sandbox_dir)

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        sandbox_dir = self._resolve_cwd()
        req_id = f"chatcmpl-cli"
        try:
            args = to_cli_args(
                req.model_copy(update={"stream": True}),
                sandbox_dir=sandbox_dir,
                settings=self._settings,
                req_id=req_id,
            )
            async for event in self.run_stream(args):
                chunk = to_sse_chunk(
                    event, req_id=req_id, model=req.model, settings=self._settings
                )
                if chunk is not None:
                    yield chunk
            yield "data: [DONE]\n\n"
        except GrokRunError as e:
            err = to_sse_chunk(
                {"type": "error", "message": str(e)},
                req_id=req_id,
                model=req.model,
                settings=self._settings,
            )
            if err is not None:
                yield err
            yield "data: [DONE]\n\n"
        except TimeoutError as e:
            err = to_sse_chunk(
                {"type": "error", "message": str(e)},
                req_id=req_id,
                model=req.model,
                settings=self._settings,
            )
            if err is not None:
                yield err
            yield "data: [DONE]\n\n"
        finally:
            if sandbox_dir != self._settings.grok_cwd:
                cleanup_sandbox(sandbox_dir)

    def _resolve_cwd(self) -> str:
        if self._settings.grok_cwd:
            return self._settings.grok_cwd
        return create_sandbox(root=self._settings.sandbox_root)

    def _subprocess_env(self) -> dict[str, str] | None:
        proxy = self._settings.proxy_url
        if not proxy:
            return None
        env = dict(os.environ)
        env["ALL_PROXY"] = proxy
        env["all_proxy"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["https_proxy"] = proxy
        env["HTTP_PROXY"] = proxy
        env["http_proxy"] = proxy
        return env

    async def run(self, args: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._settings.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await self._reap(proc)
            raise TimeoutError(f"grok timed out after {self._settings.timeout}s") from None

        assert proc.returncode is not None
        rc = proc.returncode
        if rc != 0:
            stderr_str = stderr.decode(errors="replace") if stderr else ""
            raise GrokRunError(
                f"grok exited with code {rc}: {stderr_str[-500:]}",
                rc,
                stderr_str,
            )

        stdout_str = stdout.decode(errors="replace").strip()
        if not stdout_str:
            raise GrokRunError("grok produced no output", rc, "")
        return json.loads(stdout_str)

    async def run_stream(self, args: list[str]) -> AsyncIterator[dict]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
        )
        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._settings.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await self._reap(proc)
                raise TimeoutError(f"grok timed out after {self._settings.timeout}s") from None

            assert proc.returncode is not None
            rc = proc.returncode
            if rc != 0:
                stderr_data = await proc.stderr.read() if proc.stderr else b""
                stderr_str = stderr_data.decode(errors="replace")
                raise GrokRunError(
                    f"grok exited with code {rc}: {stderr_str[-500:]}",
                    rc,
                    stderr_str,
                )

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)
        except asyncio.TimeoutError:
            pass
