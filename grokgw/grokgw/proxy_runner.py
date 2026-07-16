from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from grokgw.auth import AuthError, ensure_access_token
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest


class ProxyRunner:
    """OpenAI-compatible upstream via curl subprocess — reuses socks5h proxy like vpn."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_curl(self, req: ChatCompletionRequest, stream: bool) -> list[str]:
        try:
            token = ensure_access_token(self._settings.auth_path)
        except AuthError as e:
            raise GrokRunError(str(e), 401, str(e)) from e

        payload = json.dumps({
            "model": "grok-4.5" if req.model == "grok-latest" else req.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": stream,
            **({} if req.reasoning_effort is None else {"reasoning_effort": req.reasoning_effort}),
        })

        cmd = [
            "curl", "-sS",
            "--max-time", str(self._settings.timeout),
        ]
        if self._settings.proxy_url:
            cmd += ["-x", self._settings.proxy_url]
        cmd += [
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
        ]
        if stream:
            cmd.append("-N")
        cmd += [
            "-d", payload,
            f"{self._settings.upstream_base}/chat/completions",
        ]
        return cmd

    async def complete(self, req: ChatCompletionRequest) -> dict:
        cmd = self._build_curl(req.model_copy(update={"stream": False}), stream=False)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._settings.timeout + 5,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"upstream timed out after {self._settings.timeout}s") from None

        stdout_str = stdout.decode(errors="replace").strip()
        stderr_str = stderr.decode(errors="replace") if stderr else ""

        if not stdout_str:
            raise GrokRunError(f"upstream empty: {stderr_str[-300:]}", proc.returncode or 502, stderr_str)
        try:
            data = json.loads(stdout_str)
        except json.JSONDecodeError:
            raise GrokRunError(f"upstream invalid JSON: {stdout_str[:300]}", 502, stdout_str) from None

        if "error" in data and isinstance(data["error"], dict):
            msg = data["error"].get("message", str(data["error"]))
            status = 401 if any(k in msg.lower() for k in ("auth", "key", "unauthorized", "expired")) else 502
            raise GrokRunError(f"upstream error: {msg}", status, msg)
        if "error" in data and isinstance(data["error"], str):
            raise GrokRunError(f"upstream error: {data['error']}", 502, data["error"])

        return data

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        cmd = self._build_curl(req.model_copy(update={"stream": True}), stream=True)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                decoded = line.decode(errors="replace").rstrip("\n")
                if decoded.startswith("data:"):
                    yield decoded + "\n\n"
                elif decoded.strip():
                    yield f"data: {decoded}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._settings.timeout + 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
