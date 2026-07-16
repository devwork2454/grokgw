from __future__ import annotations
import os
from dataclasses import dataclass


def _get_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


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

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            port=int(os.environ.get("GROKGW_PORT", "8787")),
            host=os.environ.get("GROKGW_HOST", "127.0.0.1"),
            max_concurrent=int(os.environ.get("GROKGW_MAX_CONCURRENT", "3")),
            sandbox_root=os.environ.get("GROKGW_SANDBOX_ROOT", "/tmp"),
            api_key=os.environ.get("GROKGW_API_KEY"),
            grok_bin=os.environ.get("GROKGW_GROK_BIN", "grok"),
            timeout=int(os.environ.get("GROKGW_TIMEOUT", "120")),
            expose_reasoning=_get_bool("GROKGW_EXPOSE_REASONING", False),
        )
