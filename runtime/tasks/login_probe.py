from __future__ import annotations

import json

from runtime.models import Result, RunContext
from runtime.risk import url_allowed


def run(ctx: RunContext) -> Result:
    url = ctx.params.get("url")
    selector = ctx.params.get("logged_out_selector")  # CSS
    if not url or not selector:
        return Result(ok=False, message="need params.url and logged_out_selector")
    if not url_allowed(url, ctx.allowed_prefixes):
        return Result(ok=False, message="policy_violation: url not in allowlist")
    ctx.tab.get(url, timeout=int(ctx.params.get("timeout", 30)))
    # Embed selector safely via json.dumps to avoid quote/injection bugs
    sel_js = json.dumps(selector)
    found = bool(
        ctx.tab.run_js(f"return !!document.querySelector({sel_js});")
    )
    if found:
        return Result(
            ok=False, need_relogin=True, message="logged_out_selector present"
        )
    return Result(ok=True, message="session seems logged in")
