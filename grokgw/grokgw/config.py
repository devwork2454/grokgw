from __future__ import annotations
import os
from dataclasses import dataclass


def _get_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


_DEFAULT_PROXY = "socks5h://127.0.0.1:2080"
_DEFAULT_UPSTREAM = "https://api.x.ai/v1"
_DEFAULT_AUTH = os.path.expanduser("~/.grok/auth.json")
_VALID_PROXY_MODES = frozenset({"auto", "always", "never"})


def _proxy_from_env() -> str | None:
    if "GROKGW_PROXY_URL" not in os.environ:
        return _DEFAULT_PROXY
    raw = os.environ["GROKGW_PROXY_URL"].strip()
    return raw or None


@dataclass(frozen=True)
class Settings:
    port: int = 8787
    host: str = "127.0.0.1"
    max_concurrent: int = 3
    sandbox_root: str = "/tmp"
    api_key: str | None = None
    grok_bin: str = "grok"
    timeout: int = 120
    expose_reasoning: bool = False
    proxy_url: str | None = _DEFAULT_PROXY
    proxy_mode: str = "auto"  # auto | always | never
    backend: str = "proxy"  # proxy | cli
    upstream_base: str = _DEFAULT_UPSTREAM
    auth_path: str = _DEFAULT_AUTH

    @classmethod
    def from_env(cls) -> Settings:
        backend = os.environ.get("GROKGW_BACKEND", "proxy").strip().lower() or "proxy"
        if backend not in ("proxy", "cli"):
            backend = "proxy"
        proxy_mode = os.environ.get("GROKGW_PROXY_MODE", "auto").strip().lower()
        if proxy_mode not in _VALID_PROXY_MODES:
            proxy_mode = "auto"
        return cls(
            port=int(os.environ.get("GROKGW_PORT", "8787")),
            host=os.environ.get("GROKGW_HOST", "127.0.0.1"),
            max_concurrent=int(os.environ.get("GROKGW_MAX_CONCURRENT", "3")),
            sandbox_root=os.environ.get("GROKGW_SANDBOX_ROOT", "/tmp"),
            api_key=os.environ.get("GROKGW_API_KEY"),
            grok_bin=os.environ.get("GROKGW_GROK_BIN", "grok"),
            timeout=int(os.environ.get("GROKGW_TIMEOUT", "120")),
            expose_reasoning=_get_bool("GROKGW_EXPOSE_REASONING", False),
            proxy_url=_proxy_from_env(),
            proxy_mode=proxy_mode,
            backend=backend,
            upstream_base=os.environ.get("GROKGW_UPSTREAM_BASE", _DEFAULT_UPSTREAM).rstrip("/"),
            auth_path=os.environ.get("GROKGW_AUTH_PATH", _DEFAULT_AUTH),
        )
