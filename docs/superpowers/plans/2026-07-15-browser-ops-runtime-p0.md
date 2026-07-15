# Browser Ops Runtime P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本仓落地单机 P0 浏览器运营运行时：SQLite 元数据 + 每账号独立 Chrome profile + 代理绑定 + 进程内 interval 调度 + 基础风控 + CLI，并保留 antibot 回归入口。

**Architecture:** 进程内模块化单体。`Store` 管 SQLite；`Risk` 做并发/冷却/allowlist/代理熔断；`BrowserRuntime` 从 `antibot/run_takeover.py` 固化接管启动（强制 `ChromiumOptions.headless(True)`）；`SessionManager` 管 profile 锁与代理解析；`Scheduler` 调任务脚本；`CLI` 为唯一运营入口。运营 profile 永不删除；研究回归用临时目录。

**Tech Stack:** Python 3.12、stdlib `sqlite3` / `argparse` / `subprocess`、本地 DrissionPage 5.0.0b0（`antibot/.venv`）、Google Chrome headless、socks5 代理（默认 `127.0.0.1:2080`）。

**Spec:** `docs/superpowers/specs/2026-07-15-browser-ops-runtime-design.md`

**Notes for agents:**
- 工作区当前 **不是 git 仓库**。凡 “Commit” 步骤：若无 `.git` 则跳过并打印 `SKIP commit (no git repo)`。
- 浏览器相关集成测试需要本机 Chrome + 代理监听；单元测试不启浏览器。
- 激活 venv：`source antibot/.venv/bin/activate`；在仓库根执行 `python -m runtime ...`（需 `PYTHONPATH=.` 或从根安装 editable；计划采用 **仓库根为 cwd 且 `python -m runtime`**，`runtime` 包在根下）。
- 不要引入 Web UI、分布式、Xvfb、多引擎。
- 不要把「过 Cloudflare」写入成功标准。

---

## File map (create / modify)

| Path | Responsibility |
|------|----------------|
| `runtime/__init__.py` | 包标记；`__version__ = "0.1.0"` |
| `runtime/__main__.py` | `python -m runtime` → `cli.main` |
| `runtime/paths.py` | `ROOT` / `DATA` / `DB_PATH` / `PROFILES` / `SECRETS` / `LOGS` |
| `runtime/schema.sql` | 表定义 |
| `runtime/models.py` | dataclass：Account, Proxy, Task, TaskRun, SitePolicy, Result, RunContext |
| `runtime/store.py` | SQLite CRUD + schema init |
| `runtime/risk.py` | allowlist、并发槽、冷却、节流、代理熔断判定 |
| `runtime/ports.py` | 调试端口池 9600–9699 |
| `runtime/browser.py` | BrowserRuntime：spawn / attach / stealth / cleanup |
| `runtime/session.py` | profile 文件锁、组装 Runtime 参数 |
| `runtime/runner.py` | 加载任务脚本、执行一次 run、写 task_runs/审计 |
| `runtime/scheduler.py` | interval 循环、`--once` / `--loop` |
| `runtime/audit.py` | JSONL 审计追加 |
| `runtime/cli.py` | argparse 子命令 |
| `runtime/tasks/__init__.py` | |
| `runtime/tasks/healthcheck.py` | 内置任务 |
| `runtime/tasks/login_probe.py` | 内置任务 |
| `runtime/tasks/local_storage_mark.py` | 隔离验收用任务（写/读 localStorage） |
| `runtime/tests/test_store.py` | 无浏览器 |
| `runtime/tests/test_risk.py` | 无浏览器 |
| `runtime/tests/test_browser_contract.py` | 静态契约（headless workaround） |
| `runtime/tests/test_runner_unit.py` | mock tab 可选 |
| `.gitignore` | 忽略 `data/` |
| `AGENTS.md` | 增加 runtime 入口说明 |
| `antibot/stealth_min.js` | **只读引用**；Runtime 通过路径读取，不复制内容分叉 |

**Do not modify in P0 (except optional thin later):** `antibot/run_takeover.py` 保持可独立运行；`regress` 子进程调用它即可。

---

### Task 1: Scaffold paths, schema, models, gitignore

**Files:**
- Create: `runtime/__init__.py`
- Create: `runtime/paths.py`
- Create: `runtime/schema.sql`
- Create: `runtime/models.py`
- Create: `.gitignore` (or append if exists)
- Create: `runtime/tests/test_models_import.py`

- [ ] **Step 1: Write the failing import test**

```python
# runtime/tests/test_models_import.py
from runtime.models import Result, Account
from runtime.paths import DATA, DB_PATH

def test_result_defaults():
    r = Result(ok=True)
    assert r.ok is True
    assert r.need_relogin is False
    assert r.retryable is False
    assert r.message == ""

def test_data_paths_under_repo():
    assert DATA.name == "data"
    assert DB_PATH.name == "xpage.db"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -c "from runtime.models import Result"  # expect ModuleNotFoundError or ImportError
```

Expected: import fails.

- [ ] **Step 3: Implement scaffold**

`runtime/__init__.py`:
```python
__version__ = "0.1.0"
```

`runtime/paths.py`:
```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "xpage.db"
PROFILES = DATA / "profiles"
SECRETS = DATA / "secrets"
LOGS = DATA / "logs"
AUDIT_LOG = LOGS / "audit.jsonl"
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
STEALTH_MIN_JS = ROOT / "antibot" / "stealth_min.js"

def ensure_data_dirs() -> None:
    for p in (DATA, PROFILES, SECRETS, LOGS):
        p.mkdir(parents=True, exist_ok=True)
```

`runtime/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS proxies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  scheme TEXT NOT NULL DEFAULT 'socks5',
  host TEXT NOT NULL,
  port INTEGER NOT NULL,
  auth_ref TEXT,
  health TEXT NOT NULL DEFAULT 'unknown',
  last_check_at TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  site_key TEXT NOT NULL,
  username TEXT,
  secret_ref TEXT,
  profile_path TEXT NOT NULL,
  proxy_id INTEGER REFERENCES proxies(id),
  status TEXT NOT NULL DEFAULT 'active',
  last_ok_at TEXT,
  last_error TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  fail_streak INTEGER NOT NULL DEFAULT 0,
  cooling_until TEXT
);

CREATE TABLE IF NOT EXISTS site_policies (
  site_key TEXT PRIMARY KEY,
  url_allow_prefix TEXT NOT NULL DEFAULT '[]',
  min_interval_sec INTEGER NOT NULL DEFAULT 0,
  max_concurrency INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  script TEXT NOT NULL,
  schedule TEXT NOT NULL DEFAULT 'interval:300',
  enabled INTEGER NOT NULL DEFAULT 1,
  max_retries INTEGER NOT NULL DEFAULT 2,
  timeout_sec INTEGER NOT NULL DEFAULT 120,
  params_json TEXT NOT NULL DEFAULT '{}',
  last_started_at TEXT
);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  error TEXT,
  log_path TEXT
);
```

`runtime/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Result:
    ok: bool
    need_relogin: bool = False
    retryable: bool = False
    message: str = ""


@dataclass
class Proxy:
    id: int
    name: str
    scheme: str
    host: str
    port: int
    auth_ref: Optional[str] = None
    health: str = "unknown"
    last_check_at: Optional[str] = None

    def proxy_url(self) -> str:
        # auth 在 P0 先不拼进 URL（auth_ref 留给后续）；格式 scheme://host:port
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass
class Account:
    id: int
    name: str
    site_key: str
    username: Optional[str]
    secret_ref: Optional[str]
    profile_path: str
    proxy_id: Optional[int]
    status: str = "active"
    last_ok_at: Optional[str] = None
    last_error: Optional[str] = None
    meta_json: str = "{}"
    fail_streak: int = 0
    cooling_until: Optional[str] = None


@dataclass
class SitePolicy:
    site_key: str
    url_allow_prefixes: list[str] = field(default_factory=list)
    min_interval_sec: int = 0
    max_concurrency: int = 1


@dataclass
class Task:
    id: int
    name: str
    account_id: int
    script: str
    schedule: str
    enabled: bool = True
    max_retries: int = 2
    timeout_sec: int = 120
    params_json: str = "{}"
    last_started_at: Optional[str] = None


@dataclass
class TaskRun:
    id: int
    task_id: int
    started_at: str
    finished_at: Optional[str]
    status: str
    error: Optional[str] = None
    log_path: Optional[str] = None


@dataclass
class RunContext:
    tab: Any
    account: Account
    params: dict
    logger: Any
    allowed_prefixes: list[str]
```

`.gitignore`（仓库根，若不存在则创建；若存在则追加）:
```
data/
__pycache__/
*.pyc
.venv/
antibot/.venv/
```

- [ ] **Step 4: Run tests**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -m pytest runtime/tests/test_models_import.py -v
# 若无 pytest: python -c "
from runtime.models import Result
from runtime.paths import DATA, DB_PATH
assert Result(ok=True).message == ''
assert DATA.name == 'data'
print('PASS')
"
```

Expected: PASS

- [ ] **Step 5: Commit (optional)**

```bash
# only if git repo exists
git add runtime/ .gitignore && git commit -m "feat(runtime): scaffold paths, schema, models"
# else: echo 'SKIP commit (no git repo)'
```

---

### Task 2: Store (SQLite CRUD)

**Files:**
- Create: `runtime/store.py`
- Create: `runtime/tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# runtime/tests/test_store.py
import os
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
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest runtime/tests/test_store.py -v
```

Expected: FAIL (Store missing)

- [ ] **Step 3: Implement `runtime/store.py`**

实现要点：
- `__init__(self, db_path=None)` 默认 `paths.DB_PATH`
- `init_db()`：`ensure_data_dirs()`，执行 `schema.sql`
- `add_proxy` / `list_proxies` / `get_proxy` / `set_proxy_health`
- `add_account`：创建 `PROFILES / str(id)` —— 因 id 自增，可先 insert 再 `UPDATE profile_path` 为 `str(PROFILES / str(id))` 并 `mkdir`
- `get_account` / `get_account_by_name` / `list_accounts` / `update_account_status` / `bump_fail_streak` / `clear_fail_streak` / `set_cooling`
- `set_policy` / `get_policy`：`url_allow_prefix` 用 `json.dumps` / `loads`
- `add_task` / `get_task_by_name` / `list_tasks` / `set_task_enabled` / `touch_task_started`
- `start_task_run` / `finish_task_run` / `list_recent_runs`
- `list_due_tasks()`：enabled=1；解析 `interval:N`；若 `last_started_at` 为空或距今 ≥ N 秒则 due
- 时间一律 ISO UTC 或本地 `time.strftime`，全文件一致

参考骨架：

```python
# runtime/store.py — 关键方法签名（完整实现按测试补齐）
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from runtime import paths
from runtime.models import Account, Proxy, SitePolicy, Task, TaskRun


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or paths.DB_PATH)

    def connect(self) -> sqlite3.Connection:
        paths.ensure_data_dirs()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        paths.ensure_data_dirs()
        sql = paths.SCHEMA_SQL.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(sql)

    # ... implement all methods required by tests and CLI ...
```

`list_due_tasks` 解析：

```python
def _parse_interval(schedule: str) -> Optional[int]:
    if schedule.startswith("interval:"):
        return int(schedule.split(":", 1)[1])
    return None
```

- [ ] **Step 4: Run tests PASS**

```bash
python -m pytest runtime/tests/test_store.py -v
```

- [ ] **Step 5: Commit (optional)**

```bash
git add runtime/store.py runtime/tests/test_store.py && git commit -m "feat(runtime): SQLite store CRUD" || echo SKIP
```

---

### Task 3: Risk + audit

**Files:**
- Create: `runtime/risk.py`
- Create: `runtime/audit.py`
- Create: `runtime/tests/test_risk.py`

- [ ] **Step 1: Failing tests**

```python
# runtime/tests/test_risk.py
from runtime.risk import RiskGate, url_allowed
from runtime.models import Account, Proxy, SitePolicy, Task


def test_url_allowed_prefix():
    assert url_allowed("https://example.com/a", ["https://example.com/"]) is True
    assert url_allowed("https://evil.com/", ["https://example.com/"]) is False


def test_gate_skips_cooling_account():
    risk = RiskGate(global_limit=5)
    acc = Account(id=1, name="a", site_key="s", username=None, secret_ref=None,
                  profile_path="/tmp/x", proxy_id=1, status="cooling", cooling_until="2099-01-01T00:00:00")
    proxy = Proxy(id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="ok")
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s", url_allow_prefixes=["https://example.com/"])
    decision = risk.can_run(task, acc, proxy, pol, now_ts=0)
    assert decision.allowed is False
    assert decision.reason == "account_cooling"


def test_gate_skips_bad_proxy():
    risk = RiskGate(global_limit=5)
    acc = Account(id=1, name="a", site_key="s", username=None, secret_ref=None,
                  profile_path="/tmp/x", proxy_id=1, status="active")
    proxy = Proxy(id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="bad")
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s")
    decision = risk.can_run(task, acc, proxy, pol, now_ts=0)
    assert decision.allowed is False
    assert decision.reason == "proxy_bad"


def test_concurrency_slot():
    risk = RiskGate(global_limit=1)
    assert risk.try_acquire() is True
    assert risk.try_acquire() is False
    risk.release()
    assert risk.try_acquire() is True
    risk.release()
```

- [ ] **Step 2: Run fail**

```bash
python -m pytest runtime/tests/test_risk.py -v
```

- [ ] **Step 3: Implement**

`runtime/risk.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import time

from runtime.models import Account, Proxy, SitePolicy, Task


def url_allowed(url: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False  # fail-closed: empty policy denies all navigations
    return any(url.startswith(p) for p in prefixes)


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskGate:
    def __init__(self, global_limit: int = 5, fail_threshold: int = 3, cool_seconds: int = 600):
        self.global_limit = global_limit
        self.fail_threshold = fail_threshold
        self.cool_seconds = cool_seconds
        self._inflight = 0
        self._account_locks: set[int] = set()  # account ids running
        self._site_inflight: dict[str, int] = {}
        self._last_account_start: dict[int, float] = {}

    def try_acquire(self) -> bool:
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
        if last is not None and pol.min_interval_sec > 0 and (now - last) < pol.min_interval_sec:
            return RiskDecision(False, "min_interval")
        if self._inflight >= self.global_limit:
            return RiskDecision(False, "global_concurrency")
        return RiskDecision(True, "ok")

    def mark_start(self, account: Account) -> None:
        self._account_locks.add(account.id)
        self._site_inflight[account.site_key] = self._site_inflight.get(account.site_key, 0) + 1
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
```

注意：`can_run` 与 `mark_start` 都碰 `_inflight` 时不要双计。推荐 **`can_run` 只检查不占用；真正占用用 `mark_start`/`mark_end`**。单元测试 `try_acquire` 可保留作简单槽测试；`can_run` 的 global 检查用 `_inflight` 只读。调整 `test_concurrency_slot` 与实现一致：`try_acquire/release` 独立于 `mark_start`，或删除 `try_acquire` 仅测 `mark_start` 二次失败——**实现时以「mark_start 在 can_run 通过后调用」为准**，修正测试：

```python
def test_mark_start_enforces_account_busy():
    risk = RiskGate(global_limit=5)
    acc = Account(id=1, name="a", site_key="s", username=None, secret_ref=None,
                  profile_path="/tmp/x", proxy_id=1, status="active")
    proxy = Proxy(id=1, name="p", scheme="socks5", host="127.0.0.1", port=2080, health="ok")
    task = Task(id=1, name="t", account_id=1, script="x", schedule="interval:60")
    pol = SitePolicy(site_key="s")
    assert risk.can_run(task, acc, proxy, pol).allowed
    risk.mark_start(acc)
    d2 = risk.can_run(task, acc, proxy, pol)
    assert d2.allowed is False and d2.reason == "account_busy"
    risk.mark_end(acc)
```

`runtime/audit.py`:
```python
from __future__ import annotations
import json
import time
from typing import Any

from runtime import paths


def audit(event: str, **fields: Any) -> None:
    paths.ensure_data_dirs()
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields}
    with paths.AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Tests PASS**

```bash
python -m pytest runtime/tests/test_risk.py -v
```

- [ ] **Step 5: Commit optional**

---

### Task 4: Port pool + BrowserRuntime

**Files:**
- Create: `runtime/ports.py`
- Create: `runtime/browser.py`
- Create: `runtime/tests/test_browser_contract.py`

- [ ] **Step 1: Contract tests (no live Chrome required)**

```python
# runtime/tests/test_browser_contract.py
from pathlib import Path
from runtime.browser import BrowserRuntime
import inspect

def test_browser_module_source_has_headless_workaround():
    src = Path(__file__).resolve().parents[1] / "browser.py"
    text = src.read_text(encoding="utf-8")
    assert ".headless(True)" in text
    assert "set_address" in text
    assert "5.0.0b0" in text

def test_stealth_path_points_to_antibot():
    from runtime.paths import STEALTH_MIN_JS
    assert STEALTH_MIN_JS.name == "stealth_min.js"
    assert STEALTH_MIN_JS.parent.name == "antibot"
```

- [ ] **Step 2: Run fail then implement**

`runtime/ports.py`:
```python
from __future__ import annotations
import socket
from typing import Optional

_PORT_MIN = 9600
_PORT_MAX = 9699
_in_use: set[int] = set()


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def acquire_port() -> int:
    for p in range(_PORT_MIN, _PORT_MAX + 1):
        if p in _in_use:
            continue
        if _free(p):
            _in_use.add(p)
            return p
    raise RuntimeError("no free debugging port in 9600-9699")


def release_port(port: int) -> None:
    _in_use.discard(port)
```

`runtime/browser.py`（核心逻辑从 `antibot/run_takeover.py` 提炼）：

```python
from __future__ import annotations
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from runtime import paths
from runtime.ports import acquire_port, release_port


def wait_port(port: int, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@dataclass
class BrowserSession:
    port: int
    proc: subprocess.Popen
    browser: object  # Chromium
    tab: object
    profile_dir: Path
    ephemeral: bool


class BrowserRuntime:
    def start(
        self,
        profile_dir: Path,
        proxy_url: str,
        *,
        stealth: bool = True,
        ephemeral: bool = False,
    ) -> BrowserSession:
        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        port = acquire_port()
        # 清理同端口残留
        subprocess.run(["pkill", "-9", "-f", f"remote-debugging-port={port}"], timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        cmd = [
            "google-chrome",
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--proxy-server={proxy_url}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={str(profile_dir)}",
            "about:blank",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_port(port, 30):
            proc.kill()
            release_port(port)
            raise RuntimeError(f"Chrome port {port} not ready")
        # 5.0.0b0 attach bug: must set .headless(True) so _is_headless matches HeadlessChrome
        from DrissionPage import Chromium, ChromiumOptions
        browser = Chromium(ChromiumOptions().set_address(f"127.0.0.1:{port}").headless(True))
        tab = browser.latest_tab
        if stealth:
            js = paths.STEALTH_MIN_JS.read_text(encoding="utf-8")
            tab.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=js)
        return BrowserSession(port=port, proc=proc, browser=browser, tab=tab,
                              profile_dir=profile_dir, ephemeral=ephemeral)

    def stop(self, session: BrowserSession) -> None:
        try:
            # best-effort
            if hasattr(session.browser, "quit"):
                session.browser.quit()
        except Exception:
            pass
        try:
            session.proc.terminate()
            session.proc.wait(timeout=5)
        except Exception:
            try:
                session.proc.kill()
            except Exception:
                pass
        subprocess.run(["pkill", "-9", "-f", f"remote-debugging-port={session.port}"],
                       timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        release_port(session.port)
        if session.ephemeral:
            import shutil
            shutil.rmtree(session.profile_dir, ignore_errors=True)
        # operational profiles: NEVER rmtree
```

- [ ] **Step 3: Contract tests PASS**

```bash
python -m pytest runtime/tests/test_browser_contract.py -v
```

- [ ] **Step 4: Manual smoke (optional if Chrome+proxy up)**

```bash
ss -tlnp | grep 2080 || echo 'proxy down — skip smoke'
python - <<'PY'
from pathlib import Path
from runtime.browser import BrowserRuntime
rt = BrowserRuntime()
s = rt.start(Path('/tmp/rt_smoke_profile'), 'socks5://127.0.0.1:2080', stealth=True, ephemeral=True)
print('tab ok', s.tab)
rt.stop(s)
print('PASS smoke')
PY
```

- [ ] **Step 5: Commit optional**

---

### Task 5: SessionManager (profile lock)

**Files:**
- Create: `runtime/session.py`
- Create: `runtime/tests/test_session_lock.py`

- [ ] **Step 1: Lock test**

```python
# runtime/tests/test_session_lock.py
import tempfile
from pathlib import Path
from runtime.session import ProfileLock

def test_profile_lock_exclusive():
    d = Path(tempfile.mkdtemp())
    with ProfileLock(d) as L1:
        raised = False
        try:
            with ProfileLock(d, timeout=0.2):
                pass
        except TimeoutError:
            raised = True
        assert raised
```

- [ ] **Step 2: Implement `ProfileLock` using `portalocker` OR stdlib**

P0 **不新增依赖**：用 `fcntl.flock`：

```python
# runtime/session.py
from __future__ import annotations
import fcntl
import time
from pathlib import Path
from typing import Optional

from runtime.browser import BrowserRuntime, BrowserSession
from runtime.models import Account, Proxy


class ProfileLock:
    def __init__(self, profile_dir: Path, timeout: float = 30.0):
        self.profile_dir = Path(profile_dir)
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.profile_dir / ".runtime.lock"
        self._fh = open(lock_path, "a+")
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    self._fh.close()
                    raise TimeoutError(f"profile busy: {self.profile_dir}")
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self._fh:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


class SessionManager:
    def __init__(self, runtime: Optional[BrowserRuntime] = None):
        self.runtime = runtime or BrowserRuntime()

    def open(self, account: Account, proxy: Proxy, *, stealth: bool = True) -> tuple[BrowserSession, ProfileLock]:
        lock = ProfileLock(Path(account.profile_path))
        lock.__enter__()
        try:
            sess = self.runtime.start(
                Path(account.profile_path),
                proxy.proxy_url(),
                stealth=stealth,
                ephemeral=False,
            )
            return sess, lock
        except Exception:
            lock.__exit__(None, None, None)
            raise

    def close(self, sess: BrowserSession, lock: ProfileLock) -> None:
        try:
            self.runtime.stop(sess)
        finally:
            lock.__exit__(None, None, None)
```

- [ ] **Step 3: Tests PASS**

```bash
python -m pytest runtime/tests/test_session_lock.py -v
```

---

### Task 6: Task scripts + runner

**Files:**
- Create: `runtime/tasks/__init__.py`
- Create: `runtime/tasks/healthcheck.py`
- Create: `runtime/tasks/login_probe.py`
- Create: `runtime/tasks/local_storage_mark.py`
- Create: `runtime/runner.py`
- Create: `runtime/tests/test_healthcheck_unit.py`

- [ ] **Step 1: Unit test healthcheck with fake tab**

```python
# runtime/tests/test_healthcheck_unit.py
from runtime.models import Account, RunContext, Result
from runtime.tasks import healthcheck

class FakeTab:
    def __init__(self):
        self.url = None
        self.title = "OK"
    def get(self, url, timeout=30):
        self.url = url
    def run_js(self, s):
        return True

def test_healthcheck_ok():
    acc = Account(id=1, name="a", site_key="s", username=None, secret_ref=None,
                  profile_path="/tmp/x", proxy_id=1)
    ctx = RunContext(tab=FakeTab(), account=acc, params={
        "url": "https://example.com/",
        "title_contains": "OK",
    }, logger=None, allowed_prefixes=["https://example.com/"])
    r = healthcheck.run(ctx)
    assert r.ok is True

def test_healthcheck_blocks_off_policy():
    acc = Account(id=1, name="a", site_key="s", username=None, secret_ref=None,
                  profile_path="/tmp/x", proxy_id=1)
    ctx = RunContext(tab=FakeTab(), account=acc, params={"url": "https://evil.com/"},
                     logger=None, allowed_prefixes=["https://example.com/"])
    r = healthcheck.run(ctx)
    assert r.ok is False
    assert "allowlist" in r.message.lower() or "policy" in r.message.lower()
```

- [ ] **Step 2: Implement tasks + runner**

`runtime/tasks/healthcheck.py`:
```python
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
```

`runtime/tasks/login_probe.py`:
```python
from runtime.models import Result, RunContext
from runtime.risk import url_allowed

def run(ctx: RunContext) -> Result:
    url = ctx.params.get("url")
    selector = ctx.params.get("logged_out_selector")  # CSS
    if not url or not selector:
        return Result(ok=False, message="need params.url and logged_out_selector")
    if not url_allowed(url, ctx.allowed_prefixes):
        return Result(ok=False, message="policy_violation: url not in allowlist")
    ctx.tab.get(url, timeout=30)
    # DrissionPage: tab.ele(selector, timeout=2) may return None element
    try:
        el = ctx.tab.ele(selector, timeout=2)
        found = el is not None and getattr(el, "states", None) is not None
        # simpler: run_js
    except Exception:
        found = False
    found = bool(ctx.tab.run_js(
        "return !!document.querySelector(arguments[0]);", selector
    )) if False else bool(ctx.tab.run_js(
        f"return !!document.querySelector({selector!r});"
    ))
    if found:
        return Result(ok=False, need_relogin=True, message="logged_out_selector present")
    return Result(ok=True, message="session seems logged in")
```

（实现时用 `json.dumps(selector)` 安全嵌入 JS，避免引号 bug。）

`runtime/tasks/local_storage_mark.py`（验收 V2）:
```python
from runtime.models import Result, RunContext
from runtime.risk import url_allowed

def run(ctx: RunContext) -> Result:
    url = ctx.params.get("url", "https://example.com/")
    key = ctx.params.get("key", "xpage_mark")
    value = ctx.params.get("value", ctx.account.name)
    mode = ctx.params.get("mode", "write")  # write|read
    if not url_allowed(url, ctx.allowed_prefixes):
        return Result(ok=False, message="policy_violation")
    ctx.tab.get(url, timeout=30)
    if mode == "write":
        ctx.tab.run_js(f"localStorage.setItem({key!r}, {value!r});")
        return Result(ok=True, message=f"wrote {key}={value}")
    got = ctx.tab.run_js(f"return localStorage.getItem({key!r});")
    expect = ctx.params.get("expect", value)
    if got != expect:
        return Result(ok=False, message=f"expected {expect!r} got {got!r}")
    return Result(ok=True, message=f"read ok {got!r}")
```

`runtime/runner.py`:
```python
from __future__ import annotations
import importlib
import json
import traceback
from typing import Optional

from runtime.audit import audit
from runtime.models import Account, Proxy, Result, RunContext, SitePolicy, Task
from runtime.risk import RiskGate
from runtime.session import SessionManager
from runtime.store import Store


def load_task_callable(script: str):
    mod = importlib.import_module(script)
    if not hasattr(mod, "run"):
        raise RuntimeError(f"{script} has no run(ctx)")
    return mod.run


def execute_task(
    store: Store,
    risk: RiskGate,
    session_mgr: SessionManager,
    task: Task,
    *,
    stealth: bool = True,
) -> Result:
    account = store.get_account(task.account_id)
    proxy = store.get_proxy(account.proxy_id) if account.proxy_id else None
    policy = store.get_policy(account.site_key)
    decision = risk.can_run(task, account, proxy, policy)
    if not decision.allowed:
        rid = store.start_task_run(task.id)
        store.finish_task_run(rid, status="skipped_circuit", error=decision.reason)
        audit("task_skipped", task=task.name, account=account.name, reason=decision.reason)
        return Result(ok=False, message=f"skipped:{decision.reason}")

    risk.mark_start(account)
    rid = store.start_task_run(task.id)
    store.touch_task_started(task.id)
    sess = None
    lock = None
    try:
        sess, lock = session_mgr.open(account, proxy, stealth=stealth)
        params = json.loads(task.params_json or "{}")
        prefixes = policy.url_allow_prefixes if policy else []
        ctx = RunContext(tab=sess.tab, account=account, params=params, logger=None,
                         allowed_prefixes=prefixes)
        fn = load_task_callable(task.script)
        result: Result = fn(ctx)
        # retries for retryable left to scheduler layer; single attempt here OR loop max_retries
        status = "ok" if result.ok else "fail"
        store.finish_task_run(rid, status=status, error=result.message or None)
        if result.ok:
            store.clear_fail_streak(account.id)
        else:
            store.bump_fail_streak(account.id)
            if result.need_relogin:
                store.update_account_status(account.id, "need_relogin", result.message)
        audit("task_done", task=task.name, account=account.name, ok=result.ok,
              message=result.message)
        return result
    except Exception as e:
        store.finish_task_run(rid, status="fail", error=str(e))
        store.bump_fail_streak(account.id)
        audit("task_error", task=task.name, account=account.name, error=str(e))
        return Result(ok=False, retryable=True, message=str(e))
    finally:
        if sess is not None and lock is not None:
            session_mgr.close(sess, lock)
        risk.mark_end(account)
```

（`Store` 方法名与 Task 2 对齐；缺的在本任务补齐。）

- [ ] **Step 3: Unit tests PASS**

```bash
python -m pytest runtime/tests/test_healthcheck_unit.py -v
```

---

### Task 7: CLI — doctor, proxy, account, policy, task, status

**Files:**
- Create: `runtime/cli.py`
- Create: `runtime/__main__.py`

- [ ] **Step 1: Implement CLI with argparse**

`runtime/__main__.py`:
```python
from runtime.cli import main
raise SystemExit(main())
```

`runtime/cli.py` 子命令最小行为：

| Command | Behavior |
|---------|----------|
| `doctor` | 检查：Chrome 可执行？`DrissionPage` 模块路径含本地？`ss`/连接 `127.0.0.1:2080`？`data/` 可写？打印 OK/FAIL 行 |
| `proxy add --name --host --port [--scheme socks5]` | store.add_proxy |
| `proxy list` | 表格打印 |
| `proxy check --name` | TCP connect host:port 或对 socks 仅 TCP；更新 health |
| `account add --name --site-key --username [--proxy-name] [--secret-ref]` | add_account |
| `account list` | |
| `policy set --site-key --allow PREFIX [PREFIX...] [--min-interval N]` | |
| `policy show --site-key` | |
| `task add --name --account --script --interval SEC [--param key=val]` | schedule=`interval:{SEC}`，params JSON |
| `task list` | |
| `status` | accounts + recent runs |

doctor 伪代码片段：
```python
def cmd_doctor(_args):
    from DrissionPage import Chromium
    ok_dp = "chromium" in Chromium.__module__
    print(f"[{'OK' if ok_dp else 'FAIL'}] DrissionPage module={Chromium.__module__}")
    # chrome
    import shutil
    chrome = shutil.which("google-chrome") or shutil.which("chromium-browser")
    print(f"[{'OK' if chrome else 'FAIL'}] chrome={chrome}")
    # proxy 2080
    import socket
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 2080)); proxy_ok = True
    except Exception:
        proxy_ok = False
    finally:
        s.close()
    print(f"[{'OK' if proxy_ok else 'FAIL'}] socks/proxy 127.0.0.1:2080")
    return 0 if (ok_dp and chrome) else 1
```

- [ ] **Step 2: Manual CLI smoke**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -m runtime doctor
python -m runtime proxy add --name local --host 127.0.0.1 --port 2080
python -m runtime account add --name demo --site-key local-demo --username demo --proxy-name local
python -m runtime policy set --site-key local-demo --allow https://example.com/
python -m runtime task add --name hc --account demo --script runtime.tasks.healthcheck --interval 300 --param url=https://example.com/ --param title_contains=Example
python -m runtime status
```

Expected: 无 traceback；db 出现在 `data/xpage.db`。

- [ ] **Step 3: Commit optional**

---

### Task 8: `run --once` / `run --loop` + scheduler retries

**Files:**
- Create: `runtime/scheduler.py`
- Modify: `runtime/cli.py`（挂载 run）

- [ ] **Step 1: Implement scheduler**

```python
# runtime/scheduler.py
from __future__ import annotations
import time
from runtime.runner import execute_task
from runtime.risk import RiskGate
from runtime.session import SessionManager
from runtime.store import Store


def run_once(store: Store, task_name: str, risk: RiskGate | None = None) -> int:
    risk = risk or RiskGate()
    sm = SessionManager()
    task = store.get_task_by_name(task_name)
    if not task:
        print(f"unknown task {task_name}")
        return 2
    # simple retry loop
    attempt = 0
    while True:
        attempt += 1
        result = execute_task(store, risk, sm, task)
        if result.ok:
            print(f"OK {task_name}: {result.message}")
            return 0
        if result.message.startswith("skipped:"):
            print(f"SKIP {task_name}: {result.message}")
            return 0
        if result.retryable and attempt <= task.max_retries:
            time.sleep(min(2 ** attempt, 30))
            continue
        print(f"FAIL {task_name}: {result.message}")
        return 1


def run_loop(store: Store, risk: RiskGate | None = None, tick_sec: float = 5.0) -> None:
    risk = risk or RiskGate()
    sm = SessionManager()
    print("scheduler loop started")
    while True:
        for task in store.list_due_tasks():
            execute_task(store, risk, sm, task)
        time.sleep(tick_sec)
```

CLI:
```python
# run --once NAME | run --loop
```

- [ ] **Step 2: Integration smoke（需 Chrome+proxy）**

```bash
python -m runtime run --once hc
```

Expected: 打开 example.com 或按 policy 成功/明确失败信息。

- [ ] **Step 3: Commit optional**

---

### Task 9: `session login`（人在环）

**Files:**
- Modify: `runtime/cli.py`

- [ ] **Step 1: Implement**

行为：
1. 加载 account + proxy
2. `BrowserRuntime.start(profile, proxy, stealth=True, ephemeral=False)`
3. 若 `--url` 提供则 `tab.get(url)`（必须过 allowlist）
4. 打印：`Profile ready on port {port}. Complete login in this headless session is limited.`
5. **诚实限制：** 无显示环境下无法人工点网页。P0 实现两种模式：
   - **A（默认）:** `--seed-js` 可选，执行 JS 写入 cookie/localStorage 标记模拟已登录（用于验收 V3）
   - **B:** `--url` + 等待 `--wait-sec`（默认 5）后退出保存 profile（供已有自动化登录脚本后续扩展）

```python
def cmd_session_login(args):
    store = Store(); store.init_db()
    acc = store.get_account_by_name(args.account)
    proxy = store.get_proxy(acc.proxy_id)
    policy = store.get_policy(acc.site_key)
    from runtime.session import SessionManager
    sm = SessionManager()
    sess, lock = sm.open(acc, proxy, stealth=True)
    try:
        if args.url:
            from runtime.risk import url_allowed
            prefixes = policy.url_allow_prefixes if policy else []
            if not url_allowed(args.url, prefixes):
                raise SystemExit("url not allowlisted")
            sess.tab.get(args.url)
        if args.seed_js:
            sess.tab.run_js(args.seed_js)
        time.sleep(args.wait_sec)
        print(f"session saved under {acc.profile_path}")
    finally:
        sm.close(sess, lock)
```

文档字符串写明：真·人工登录需有显示或远程调试转发（P1）。

- [ ] **Step 2: V3-style smoke with seed**

```bash
python -m runtime session login demo --url https://example.com/ --seed-js 'localStorage.setItem("auth","1")' --wait-sec 2
python -m runtime task add --name probe --account demo --script runtime.tasks.local_storage_mark --interval 9999 --param url=https://example.com/ --param mode=read --param key=auth --param expect=1
python -m runtime run --once probe
```

Expected: read ok（会话持久化）。

---

### Task 10: `regress detect|monitor`

**Files:**
- Modify: `runtime/cli.py`

- [ ] **Step 1: Implement subprocess wrapper**

```python
def cmd_regress(args):
    import subprocess, sys
    from runtime.paths import ROOT, PROFILES
    antibot = ROOT / "antibot"
    # ensure operational profiles untouched: regress uses antibot scripts' own temp dirs
    before = set(p.name for p in PROFILES.glob("*")) if PROFILES.exists() else set()
    if args.what == "detect":
        cmd = [sys.executable, str(antibot / "run_takeover.py"), "hardened"]
    else:
        cmd = [sys.executable, str(antibot / "run_monitor.py")]
    print("running", cmd)
    r = subprocess.run(cmd, cwd=str(antibot))
    after = set(p.name for p in PROFILES.glob("*")) if PROFILES.exists() else set()
    if after - before:
        print("FAIL: regress mutated data/profiles:", after - before)
        return 1
    return r.returncode
```

- [ ] **Step 2: Run when proxy+chrome available**

```bash
python -m runtime regress detect
```

- [ ] **Step 3: Commit optional**

---

### Task 11: Docs — AGENTS.md runtime section

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Append section**

```markdown
## Browser Ops Runtime (P0)

- Package: `runtime/` — operational multi-account browser runtime (not antibot lab).
- Data: `data/` (gitignored) — sqlite, profiles, secrets, logs.
- Entry: from repo root with venv active:
  ```bash
  source antibot/.venv/bin/activate
  python -m runtime doctor
  python -m runtime run --once <task>
  python -m runtime run --loop
  python -m runtime regress detect
  ```
- Spec: `docs/superpowers/specs/2026-07-15-browser-ops-runtime-design.md`
- Plan: `docs/superpowers/plans/2026-07-15-browser-ops-runtime-p0.md`
- Never rmtree `data/profiles/*` operational dirs.
- Antibot scripts remain the fingerprint lab; prefer `runtime regress` for regression.
```

- [ ] **Step 2: Done**

---

### Task 12: Acceptance matrix execution (V1–V8 checklist)

**Files:**
- Create: `runtime/tests/ACCEPTANCE.md`（勾选记录）

- [ ] **Step 1: Run and record**

| ID | Command / procedure | Pass? |
|----|---------------------|-------|
| V1 | `python -m runtime doctor` | |
| V2 | 两 account 各 `local_storage_mark` write 不同 value，互 read 失败/不串 | |
| V3 | session login seed + read 仍在 | |
| V4 | 两 proxy（若仅一代理可 mock 第二为 bad/不同 port 文档说明限制） | |
| V5 | `--loop` 短 interval 跑 ≥10 次 healthcheck（可人工停） | |
| V6 | `proxy` health 置 bad 后 task skip，另一账号仍跑 | |
| V7 | healthcheck 指向非 allow 前缀 → fail + audit 行 | |
| V8 | `regress detect` 后 `data/profiles` 无新增 | |

V4 若环境只有一个真实代理：用 **假 port 代理** 验证「不同 proxy_id 写入 Chrome 的 `--proxy-server` 字符串不同」的单元/日志断言，并在 ACCEPTANCE 注明完整双出口需第二代理。

- [ ] **Step 2: Fill ACCEPTANCE.md with results and date**

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| SQLite entities | T1–T2 |
| BrowserRuntime + headless workaround | T4 |
| Profile lock / no rmtree ops profiles | T5, T4.stop |
| Risk: concurrency, cooling, proxy, allowlist | T3, T6 |
| Interval scheduler | T2 list_due + T8 |
| CLI surface | T7–T10 |
| Human/session seed login | T9 |
| Regress isolation | T10 |
| V1–V8 | T12 |
| No Web UI / distributed / Xvfb | honored (non-goals) |
| secret_ref files 0600 | implement in `account add` when writing secrets — **add in T7** when `--password-file` used |

**Gap fix folded into T7:** if `--secret-ref` points to new file, `chmod 0o600`.

**Placeholder scan:** none intentional; login_probe JS embedding must use `json.dumps`.

**Type consistency:** `Result`, `RunContext`, `Store` method names aligned across tasks.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-07-15-browser-ops-runtime-p0.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans + checkpoints  

Which approach?
