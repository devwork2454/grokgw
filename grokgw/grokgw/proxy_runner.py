from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from grokgw.auth import AuthError, ensure_access_token
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.mapping import to_upstream_chat_payload
from grokgw.models import ChatCompletionRequest

_PROBE_TIMEOUT = 8.0


class _NotSet:
    pass


class ProxyRunner:
    """Upstream chat via httpx (connection reuse + optional SOCKS/HTTP proxy)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._resolved: str | None | _NotSet = _NotSet()
        self._clients: dict[str, httpx.AsyncClient] = {}

    def _client_key(self, proxy_url: str | None) -> str:
        return proxy_url or ""

    def _make_client(self, proxy_url: str | None) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            self._settings.timeout,
            connect=min(15.0, float(self._settings.timeout)),
        )
        kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": {"Content-Type": "application/json"},
            "follow_redirects": True,
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return httpx.AsyncClient(**kwargs)

    async def _get_client(self, proxy_url: str | None) -> httpx.AsyncClient:
        key = self._client_key(proxy_url)
        client = self._clients.get(key)
        if client is None:
            client = self._make_client(proxy_url)
            self._clients[key] = client
        return client

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def _probe(self, url: str, proxy_url: str | None) -> bool:
        probe_url = url.rstrip("/") + "/models"
        try:
            timeout = httpx.Timeout(_PROBE_TIMEOUT, connect=_PROBE_TIMEOUT)
            async with httpx.AsyncClient(timeout=timeout, proxy=proxy_url) as client:
                resp = await client.get(probe_url)
            return 200 <= resp.status_code < 500
        except (httpx.HTTPError, OSError):
            return False

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

    def _auth_headers(self) -> dict[str, str]:
        try:
            token = ensure_access_token(self._settings.auth_path)
        except AuthError as e:
            raise GrokRunError(str(e), 401, str(e)) from e
        return {"Authorization": f"Bearer {token}"}

    def _chat_url(self) -> str:
        return f"{self._settings.upstream_base.rstrip('/')}/chat/completions"

    def _raise_upstream_error(self, data: dict) -> None:
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message", str(err))
            status = 401 if any(
                k in msg.lower() for k in ("auth", "key", "unauthorized", "expired")
            ) else 502
            raise GrokRunError(f"upstream error: {msg}", status, msg)
        if isinstance(err, str):
            raise GrokRunError(f"upstream error: {err}", 502, err)

    async def complete(self, req: ChatCompletionRequest) -> dict:
        proxy = await self._get_proxy()
        client = await self._get_client(proxy)
        payload = to_upstream_chat_payload(req, stream=False)
        headers = self._auth_headers()
        try:
            resp = await client.post(self._chat_url(), json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"upstream timed out after {self._settings.timeout}s") from e
        except httpx.HTTPError as e:
            raise GrokRunError(f"upstream request failed: {e}", 502, str(e)) from e

        text = resp.text
        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise GrokRunError(
                f"upstream invalid JSON: {text[:300]}",
                502,
                text,
            ) from None

        if resp.status_code >= 400 or "error" in data:
            if isinstance(data, dict) and "error" in data:
                self._raise_upstream_error(data)
            raise GrokRunError(
                f"upstream HTTP {resp.status_code}: {text[:300]}",
                resp.status_code if resp.status_code >= 400 else 502,
                text,
            )
        return data

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        proxy = await self._get_proxy()
        client = await self._get_client(proxy)
        payload = to_upstream_chat_payload(req, stream=True)
        headers = self._auth_headers()
        try:
            async with client.stream(
                "POST", self._chat_url(), json=payload, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    try:
                        data = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        data = {}
                    if isinstance(data, dict) and "error" in data:
                        self._raise_upstream_error(data)
                    raise GrokRunError(
                        f"upstream HTTP {resp.status_code}: {body[:300]}",
                        resp.status_code,
                        body,
                    )
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        yield line + "\n\n"
                    else:
                        yield f"data: {line}\n\n"
            yield "data: [DONE]\n\n"
        except httpx.TimeoutException as e:
            raise TimeoutError(f"upstream timed out after {self._settings.timeout}s") from e
        except httpx.HTTPError as e:
            raise GrokRunError(f"upstream request failed: {e}", 502, str(e)) from e
