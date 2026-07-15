from __future__ import annotations

from runtime.models import Result, RunContext
from runtime.risk import url_allowed


def run(ctx: RunContext) -> Result:
    url = ctx.params.get("url")
    if not url:
        return Result(ok=False, message="missing params.url")
    if not url_allowed(url, ctx.allowed_prefixes):
        return Result(ok=False, message="policy_violation: url not in allowlist")
    ctx.tab.get(url, timeout=int(ctx.params.get("timeout", 30)))
    title = getattr(ctx.tab, "title", "") or ""
    needle = ctx.params.get("title_contains")
    if needle and needle not in title:
        return Result(ok=False, retryable=True, message=f"title mismatch: {title!r}")
    return Result(ok=True, message=f"ok title={title!r}")
