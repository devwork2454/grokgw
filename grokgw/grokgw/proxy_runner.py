from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from grokgw.auth import AuthError, ensure_access_token
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest

_PROBE_TIMEOUT = 8


class _NotSet:
    pass


def _strip_reasoning_complete(data: dict) -> dict:
    """Remove reasoning_content from non-stream OpenAI-style responses."""
    try:
        choices = data.get("choices")
        if not isinstance(choices, list):
            return data
        new_choices = []
        changed = False
        for ch in choices:
            if not isinstance(ch, dict):
                new_choices.append(ch)
                continue
            msg = ch.get("message")
            if isinstance(msg, dict) and "reasoning_content" in msg:
                msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                ch = {**ch, "message": msg}
                changed = True
            new_choices.append(ch)
        if changed:
            return {**data, "choices": new_choices}
    except Exception:
        return data
    return data


def _strip_reasoning_sse_data(payload: str) -> str | None:
    """Filter reasoning-only stream chunks; strip reasoning fields from mixed chunks.

    Returns None if the entire chunk should be dropped (reasoning-only delta).
    """
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if not isinstance(obj, dict):
        return payload
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return payload
    new_choices = []
    keep = False
    for ch in choices:
        if not isinstance(ch, dict):
            new_choices.append(ch)
            keep = True
            continue
        delta = ch.get("delta")
        if isinstance(delta, dict):
            # drop pure reasoning tokens that only carry reasoning_content
            has_content = bool(delta.get("content"))
            has_tools = bool(delta.get("tool_calls") or delta.get("function_call"))
            has_role = bool(delta.get("role"))
            has_finish = ch.get("finish_reason") is not None
            cleaned = {k: v for k, v in delta.items() if k != "reasoning_content"}
            if not has_content and not has_tools and not has_role and not has_finish:
                # only reasoning (or empty) — skip
                if set(delta.keys()) <= {"reasoning_content", "role"} and not has_role:
                    continue
                if list(delta.keys()) == ["reasoning_content"]:
                    continue
            ch = {**ch, "delta": cleaned}
            if cleaned or has_finish:
                keep = True
        else:
            keep = True
        new_choices.append(ch)
    if not keep or not new_choices:
        return None
    return json.dumps({**obj, "choices": new_choices}, ensure_ascii=False)


class ProxyRunner:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._resolved: str | None | _NotSet = _NotSet()

    async def _probe(self, url: str, proxy_url: str | None) -> bool:
        probe_url = url.rstrip("/") + "/models"
        cmd = ["curl", "-sS", "--max-time", str(_PROBE_TIMEOUT), "-o", "/dev/null", "-w", "%{http_code}"]
        if proxy_url:
            cmd += ["-x", proxy_url]
        cmd.append(probe_url)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT + 2)
        except (asyncio.TimeoutError, OSError):
            return False
        code = stdout.decode(errors="replace").strip()
        return code.isdigit() and 200 <= int(code) < 500

    async def _resolve_proxy(self) -> str | None:
        mode = self._settings.proxy_mode
        upstream = self._settings.upstream_base
        proxy = self._settings.proxy_url
        if mode == "always":
            return proxy
        if mode == "never":
            return None
        direct_ok = await self._probe(upstream, proxy_url=None)
        if direct_ok:
            return None
        if not proxy:
            raise GrokRunError(
                "direct connection failed and no proxy configured; "
                "set GROKGW_PROXY_URL or use GROKGW_PROXY_MODE=never if you have direct access",
                502,
                "no route to upstream",
            )
        proxy_ok = await self._probe(upstream, proxy_url=proxy)
        if proxy_ok:
            return proxy
        raise GrokRunError(
            f"cannot reach {upstream} (direct and proxy both failed); "
            f"check network or GROKGW_PROXY_URL={proxy}",
            502,
            "no route to upstream",
        )

    async def _get_proxy(self) -> str | None:
        if isinstance(self._resolved, _NotSet):
            self._resolved = await self._resolve_proxy()
        return self._resolved

    def _build_curl(self, req: ChatCompletionRequest, stream: bool, proxy: str | None) -> list[str]:
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

        cmd = ["curl", "-sS", "--max-time", str(self._settings.timeout)]
        if proxy:
            cmd += ["-x", proxy]
        cmd += ["-H", f"Authorization: Bearer {token}", "-H", "Content-Type: application/json"]
        if stream:
            cmd.append("-N")
        cmd += ["-d", payload, f"{self._settings.upstream_base}/chat/completions"]
        return cmd

    async def complete(self, req: ChatCompletionRequest) -> dict:
        proxy = await self._get_proxy()
        cmd = self._build_curl(req.model_copy(update={"stream": False}), stream=False, proxy=proxy)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._settings.timeout + 5,
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
        if not self._settings.expose_reasoning:
            data = _strip_reasoning_complete(data)
        return data

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        proxy = await self._get_proxy()
        cmd = self._build_curl(req.model_copy(update={"stream": True}), stream=True, proxy=proxy)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                decoded = line.decode(errors="replace").rstrip("\n")
                if not decoded.strip():
                    continue
                # normalize to "data: ..." SSE frame body (without trailing blank line)
                if decoded.startswith("data:"):
                    payload = decoded[5:].lstrip()
                    frame = decoded
                else:
                    payload = decoded
                    frame = f"data: {decoded}"

                # drop upstream [DONE]; we emit exactly one at the end
                if payload.strip() == "[DONE]":
                    continue

                if not self._settings.expose_reasoning and payload.strip() not in ("", "[DONE]"):
                    filtered = _strip_reasoning_sse_data(payload)
                    if filtered is None:
                        continue  # reasoning-only chunk
                    frame = f"data: {filtered}"

                yield frame.rstrip("\n") + "\n\n"

            # single terminal DONE for OpenAI-compatible clients
            yield "data: [DONE]\n\n"
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._settings.timeout + 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
