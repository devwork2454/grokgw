from __future__ import annotations
import asyncio
import json
import os
from typing import AsyncIterator
from grokgw.config import Settings

_KILL_GRACE = 2


class GrokRunError(Exception):
    def __init__(self, message: str, returncode: int, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class GrokRunner:
    def __init__(self, settings: Settings):
        self._settings = settings

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
