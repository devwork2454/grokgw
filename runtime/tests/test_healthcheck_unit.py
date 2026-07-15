from runtime.models import Account, RunContext
from runtime.tasks import healthcheck


class FakeTab:
    def __init__(self):
        self.url = None
        self.title = "OK"

    def get(self, url, timeout=30):
        self.url = url


def test_healthcheck_ok():
    acc = Account(
        id=1,
        name="a",
        site_key="s",
        username=None,
        secret_ref=None,
        profile_path="/tmp/x",
        proxy_id=1,
    )
    ctx = RunContext(
        tab=FakeTab(),
        account=acc,
        params={
            "url": "https://example.com/",
            "title_contains": "OK",
        },
        logger=None,
        allowed_prefixes=["https://example.com/"],
    )
    r = healthcheck.run(ctx)
    assert r.ok is True


def test_healthcheck_blocks_off_policy():
    acc = Account(
        id=1,
        name="a",
        site_key="s",
        username=None,
        secret_ref=None,
        profile_path="/tmp/x",
        proxy_id=1,
    )
    ctx = RunContext(
        tab=FakeTab(),
        account=acc,
        params={"url": "https://evil.com/"},
        logger=None,
        allowed_prefixes=["https://example.com/"],
    )
    r = healthcheck.run(ctx)
    assert r.ok is False
    assert "allowlist" in r.message.lower() or "policy" in r.message.lower()
