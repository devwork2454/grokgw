from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from runtime.models import Account, Proxy, SitePolicy, Task


def url_allowed(url: str, prefixes: list[str]) -> bool:
    """Empty prefixes = fail-closed (deny all); else any startswith."""
    if not prefixes:
        return False
    return any(url.startswith(p) for p in prefixes)


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskGate:
    def __init__(
        self,
        global_limit: int = 5,
        fail_threshold: int = 3,
        cool_seconds: int = 600,
    ):
        self.global_limit = global_limit
        self.fail_threshold = fail_threshold
        self.cool_seconds = cool_seconds
        self._inflight = 0
        self._account_locks: set[int] = set()
        self._site_inflight: dict[str, int] = {}
        self._last_account_start: dict[int, float] = {}

    def try_acquire(self) -> bool:
        """Simple global slot helper (independent of mark_start)."""
        if self._inflight >= self.global_limit:
            return False
        self._inflight += 1
        return True

    def release(self) -> None:
        self._inflight = max(0, self._inflight - 1)

    def can_run(
        self,
        task: Task,
        account: Account,
        proxy: Optional[Proxy],
        policy: Optional[SitePolicy],
        now_ts: Optional[float] = None,
    ) -> RiskDecision:
        """Check-only: does not increment slots or locks."""
        now = time.time() if now_ts is None else now_ts
        if account.status == "disabled":
            return RiskDecision(False, "account_disabled")
        if account.status == "need_relogin":
            return RiskDecision(False, "need_relogin")
        if account.status == "cooling":
            return RiskDecision(False, "account_cooling")
        if proxy is None:
            return RiskDecision(False, "proxy_missing")
        if proxy.health == "bad":
            return RiskDecision(False, "proxy_bad")
        if account.id in self._account_locks:
            return RiskDecision(False, "account_busy")
        pol = policy or SitePolicy(site_key=account.site_key)
        site_n = self._site_inflight.get(account.site_key, 0)
        if site_n >= pol.max_concurrency:
            return RiskDecision(False, "site_concurrency")
        last = self._last_account_start.get(account.id)
        if (
            last is not None
            and pol.min_interval_sec > 0
            and (now - last) < pol.min_interval_sec
        ):
            return RiskDecision(False, "min_interval")
        if self._inflight >= self.global_limit:
            return RiskDecision(False, "global_concurrency")
        return RiskDecision(True, "ok")

    def mark_start(self, account: Account) -> None:
        self._account_locks.add(account.id)
        self._site_inflight[account.site_key] = (
            self._site_inflight.get(account.site_key, 0) + 1
        )
        self._last_account_start[account.id] = time.time()
        self._inflight += 1

    def mark_end(self, account: Account) -> None:
        self._account_locks.discard(account.id)
        n = self._site_inflight.get(account.site_key, 1) - 1
        if n <= 0:
            self._site_inflight.pop(account.site_key, None)
        else:
            self._site_inflight[account.site_key] = n
        self._inflight = max(0, self._inflight - 1)
