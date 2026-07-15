from runtime.risk import RiskGate, url_allowed
from runtime.models import Account, Proxy, SitePolicy, Task


def test_url_allowed_prefix():
    assert url_allowed("https://example.com/a", ["https://example.com/"]) is True
    assert url_allowed("https://evil.com/", ["https://example.com/"]) is False


def test_gate_skips_cooling_account():
    risk = RiskGate(global_limit=5)
    acc = Account(
        id=1,
        name="a",
        site_key="s",
        username=None,
        secret_ref=None,
        profile_path="/tmp/x",
        proxy_id=1,
        status="cooling",
        cooling_until="2099-01-01T00:00:00",
    )
    proxy = Proxy(
        id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="ok"
    )
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s", url_allow_prefixes=["https://example.com/"])
    decision = risk.can_run(task, acc, proxy, pol, now_ts=0)
    assert decision.allowed is False
    assert decision.reason == "account_cooling"


def test_gate_skips_bad_proxy():
    risk = RiskGate(global_limit=5)
    acc = Account(
        id=1,
        name="a",
        site_key="s",
        username=None,
        secret_ref=None,
        profile_path="/tmp/x",
        proxy_id=1,
        status="active",
    )
    proxy = Proxy(
        id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="bad"
    )
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s")
    decision = risk.can_run(task, acc, proxy, pol, now_ts=0)
    assert decision.allowed is False
    assert decision.reason == "proxy_bad"


def test_mark_start_enforces_account_busy():
    risk = RiskGate(global_limit=5)
    acc = Account(
        id=1,
        name="a",
        site_key="s",
        username=None,
        secret_ref=None,
        profile_path="/tmp/x",
        proxy_id=1,
        status="active",
    )
    proxy = Proxy(
        id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="ok"
    )
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s")
    assert risk.can_run(task, acc, proxy, pol).allowed
    risk.mark_start(acc)
    d2 = risk.can_run(task, acc, proxy, pol)
    assert d2.allowed is False and d2.reason == "account_busy"
    risk.mark_end(acc)
