import tempfile
from pathlib import Path

from runtime.store import Store


def _tmp_store():
    d = tempfile.mkdtemp()
    db = Path(d) / "t.db"
    return Store(db_path=db)


def test_init_and_add_proxy_account_task():
    s = _tmp_store()
    s.init_db()
    pid = s.add_proxy(name="p1", scheme="socks5", host="127.0.0.1", port=2080)
    assert pid > 0
    aid = s.add_account(name="a1", site_key="own", username="u", proxy_id=pid)
    assert aid > 0
    acc = s.get_account_by_name("a1")
    assert acc.site_key == "own"
    assert "profiles" in acc.profile_path or acc.profile_path.endswith(str(aid)) or str(aid) in acc.profile_path
    s.set_policy("own", ["https://example.com/"], min_interval_sec=10, max_concurrency=1)
    pol = s.get_policy("own")
    assert pol.url_allow_prefixes == ["https://example.com/"]
    tid = s.add_task(name="t1", account_id=aid, script="runtime.tasks.healthcheck", schedule="interval:60")
    t = s.get_task_by_name("t1")
    assert t.enabled is True
    rid = s.start_task_run(tid)
    s.finish_task_run(rid, status="ok", error=None)
    runs = s.list_recent_runs(limit=5)
    assert runs[0].status == "ok"


def test_list_due_tasks_interval():
    s = _tmp_store()
    s.init_db()
    pid = s.add_proxy(name="p1", scheme="socks5", host="127.0.0.1", port=2080)
    aid = s.add_account(name="a1", site_key="own", username="u", proxy_id=pid)
    s.add_task(name="t1", account_id=aid, script="runtime.tasks.healthcheck", schedule="interval:1")
    due = s.list_due_tasks()
    assert any(t.name == "t1" for t in due)
