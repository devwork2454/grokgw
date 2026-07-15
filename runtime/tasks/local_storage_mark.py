from __future__ import annotations

import json

from runtime.models import Result, RunContext
from runtime.risk import url_allowed


def run(ctx: RunContext) -> Result:
    url = ctx.params.get("url", "https://example.com/")
    key = ctx.params.get("key", "xpage_mark")
    value = ctx.params.get("value", ctx.account.name)
    mode = ctx.params.get("mode", "write")  # write|read
    if not url_allowed(url, ctx.allowed_prefixes):
        return Result(ok=False, message="policy_violation")
    ctx.tab.get(url, timeout=int(ctx.params.get("timeout", 30)))
    key_js = json.dumps(key)
    value_js = json.dumps(value)
    if mode == "write":
        ctx.tab.run_js(f"localStorage.setItem({key_js}, {value_js});")
        return Result(ok=True, message=f"wrote {key}={value}")
    if mode != "read":
        return Result(ok=False, message=f"unknown mode: {mode!r}")
    got = ctx.tab.run_js(f"return localStorage.getItem({key_js});")
    expect = ctx.params.get("expect", value)
    if got != expect:
        return Result(ok=False, message=f"expected {expect!r} got {got!r}")
    return Result(ok=True, message=f"read ok {got!r}")
