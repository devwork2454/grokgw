from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import uuid
from collections.abc import AsyncIterator

from grokgw.config import Settings
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.media import rewrite_media_paths
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
        # Serialize grok -p processes: concurrent CLI sessions often hang/pile up.
        self._spawn_lock = asyncio.Lock() if settings.cli_serialize else None

    async def complete(self, req: ChatCompletionRequest) -> dict:
        sandbox_dir = self._resolve_cwd()
        try:
            args = to_cli_args(
                req.model_copy(update={"stream": False}),
                sandbox_dir=sandbox_dir,
                settings=self._settings,
                req_id="cli",
            )
            if self._spawn_lock is not None:
                async with self._spawn_lock:
                    data = await self.run(args)
            else:
                data = await self.run(args)
            if self._settings.media_enabled:
                sid = data.get("sessionId") or ""
                text = data.get("text") or ""
                if sid and text:
                    data = {
                        **data,
                        "text": rewrite_media_paths(
                            text,
                            base=self._settings.public_base,
                            session_id=sid,
                        ),
                    }
            return to_openai_response(data, req)
        finally:
            if sandbox_dir != self._settings.grok_cwd:
                cleanup_sandbox(sandbox_dir)

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        sandbox_dir = self._resolve_cwd()
        req_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"
        lock = self._spawn_lock
        try:
            if lock is not None:
                await lock.acquire()
            try:
                args = to_cli_args(
                    req.model_copy(update={"stream": True}),
                    sandbox_dir=sandbox_dir,
                    settings=self._settings,
                    req_id=req_id,
                )
                try:
                    async for event in self.run_stream(args):
                        chunk = to_sse_chunk(
                            event,
                            req_id=req_id,
                            model=req.model,
                            settings=self._settings,
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
                if lock is not None and lock.locked():
                    lock.release()
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

    async def _spawn(self, args: list[str]) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
            start_new_session=True,
        )

    async def run(self, args: list[str]) -> dict:
        proc = await self._spawn(args)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._settings.timeout,
            )
        except asyncio.TimeoutError:
            await self._kill_tree(proc)
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
        try:
            return json.loads(stdout_str)
        except json.JSONDecodeError as e:
            raise GrokRunError(
                f"grok produced invalid JSON: {stdout_str[:300]}",
                rc,
                stdout_str,
            ) from e

    async def run_stream(self, args: list[str]) -> AsyncIterator[dict]:
        proc = await self._spawn(args)
        deadline = time.monotonic() + self._settings.timeout
        timed_out = False
        try:
            assert proc.stdout is not None
            aiter = proc.stdout.__aiter__()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    line = await asyncio.wait_for(aiter.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    timed_out = True
                    break

                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        finally:
            if timed_out or proc.returncode is None:
                await self._kill_tree(proc)
            else:
                await self._reap(proc)

            if timed_out:
                raise TimeoutError(f"grok timed out after {self._settings.timeout}s") from None

            assert proc.returncode is not None
            rc = proc.returncode
            if rc != 0:
                stderr_data = b""
                if proc.stderr is not None:
                    try:
                        stderr_data = await asyncio.wait_for(proc.stderr.read(), timeout=1)
                    except (asyncio.TimeoutError, Exception):
                        stderr_data = b""
                # MockProc.stderr may be bytes already
                if isinstance(proc.stderr, (bytes, bytearray)):
                    stderr_data = bytes(proc.stderr)
                stderr_str = stderr_data.decode(errors="replace") if isinstance(stderr_data, (bytes, bytearray)) else str(stderr_data)
                raise GrokRunError(
                    f"grok exited with code {rc}: {stderr_str[-500:]}",
                    rc,
                    stderr_str,
                )

    async def _kill_tree(self, proc: asyncio.subprocess.Process) -> None:
        """Kill the subprocess and its process group (grok children)."""
        if proc.returncode is not None:
            return
        pid = getattr(proc, "pid", None)
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await self._reap(proc)

    @staticmethod
    async def _reap(proc: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)
        except asyncio.TimeoutError:
            pass
