# Design: 单机浏览器运营运行时（Browser Ops Runtime）

- **Date:** 2026-07-15
- **Status:** Draft for user review (brainstorming approved sections 1–3)
- **Repo:** `xpage`（研究仓演进为「研究床 + 运营运行时」）
- **Phase covered:** P0 MVP only（P1/P2 仅预留）

---

## 1. Product positioning

### 1.1 One-liner

在 **自有 / 明确授权** 系统上，打造 **单机可运营的浏览器自动化运行时**：独立浏览器画像（profile）+ 登录态持久化 + 账号/代理绑定 + 定时任务 + 基础风控；沿用现有 DrissionPage 研究能力保证 **稳定性与指纹一致性**，而不是面向第三方站点的对抗绕过。

### 1.2 Constraints (from discovery)

| Decision | Choice |
|----------|--------|
| 使用场景 | 自有系统 / 书面授权环境 |
| MVP 闭环 | 登录态持久化 + 定时任务 |
| 规模 | 单机小规模：约 1–20 账号，同时 1–5 浏览器 |
| 技术底座 | 在本仓演进；DrissionPage 5.0.0b0 + 现有接管/stealth |
| 架构 | Profile 运行时 + SQLite + CLI/进程内调度 |
| 显示 | 无显示机，**仅 headless**；不做 Xvfb / 真有头 |
| 「过检测」 | 对内指纹稳定 + 检测站回归可观测；**不宣称**绕过 Cloudflare 等第三方 Bot 管理 |

### 1.3 Goals by layer

| Layer | Meaning | P0 |
|-------|---------|----|
| 稳定运行 | 接管启动可靠、崩溃可恢复、任务可重试 | Yes |
| 会话持久化 | 每账号独立 `user-data-dir`，Cookie/存储可复用 | Yes |
| 多账号 | 注册表 + 站点维度 + profile 不串 | Yes |
| 多代理 | 账号 → 代理映射，启动注入 `--proxy-server` | Yes |
| 定时自动化 | 进程内调度执行任务脚本 | Yes |
| 风控（运营向） | 限流、并发帽、熔断、健康、审计 | Yes（基础） |
| 「过检测」 | 检测站回归 + 自有站指纹稳定 | Yes（研究回归床） |
| 多机 / 远程看屏 | 分布式、云桌面 | No（P2+ / 非目标） |

### 1.4 Hard compliance boundaries

- 仅用于自有系统或书面授权环境。
- 默认 **URL allowlist**：禁止导航到未授权第三方生产域。
- 「过检测」**不包含**指导规避第三方商业 Bot 管理、撞库、刷量。
- 密钥 / Cookie / 代理密码：secret 引用 + 文件权限收紧；审计可追踪账号/代理/任务/URL/结果。

### 1.5 Relationship to existing antibot research

```
现有 antibot                         新产品层
├─ 接管启动 / stealth_min.js    →   BrowserRuntime
├─ BotMonitor                   →   可选：任务内异常页检测
├─ report/ 检测床               →   regress 回归套件
└─ AGENTS.md 环境坑             →   Runtime 默认策略
```

- Canonical 运营入口：`runtime` 包 + CLI。
- Canonical 研究回归：`runtime regress` 或现有 `run_takeover.py` / `run_monitor.py`（薄封装）。
- Legacy：`run_detect.py`、`run_detect2.py`、`run_hardened.py`、`run_hardened2.py` 标记废弃，不删除历史证据。

### 1.6 Phasing

| Phase | Name | Deliverable |
|-------|------|-------------|
| **P0** | Profile Runtime | SQLite + profiles + CLI + 调度 + 并发≤5 + 基础风控 |
| **P1** | 可运营 | 更强任务插件、自动重登钩子、告警完善、回归可一键 |
| **P2** | 可扩展 | API 控制面、多机 worker、细粒度站点策略 |

**本规格只钉死 P0。**

### 1.7 P0 success criteria

1. 同账号二次启动保持登录态（自有测试站或 mock）。
2. 账号 A/B 不同 proxy，出口可区分。
3. 定时任务连续成功运行（如 10 次）无 profile 串扰、无端口冲突。
4. 代理失败 / 页面错误时限流熔断生效，不拖死整机。
5. antibot 检测回归可跑，且不恶化 UA / `webdriver` 基线。

---

## 2. Architecture (P0)

### 2.1 Logical components

```
CLI → Scheduler → SessionManager → BrowserRuntime → Task Script
         │              │
         └─ Risk ───────┴─ Store (SQLite) + Audit Log
旁路: regress → antibot 临时 profile（与运营 profiles 隔离）
```

| Component | Responsibility |
|-----------|----------------|
| **CLI** | account / proxy / policy / task / run / doctor / regress / status |
| **Scheduler** | interval 调度、并发帽、重试 |
| **SessionManager** | Account→profile+proxy、profile 文件锁、健康钩子 |
| **BrowserRuntime** | spawn Chrome、CDP attach、stealth 注入、端口清理 |
| **Risk** | 冷却、代理熔断、站点节流、allowlist |
| **Store** | SQLite CRUD |
| **Task Script** | 业务步骤；返回统一 `Result` |

### 2.2 Directory layout

```
xpage/
  AGENTS.md
  antibot/                      # 研究床 + 回归
  runtime/
    __init__.py
    models.py
    store.py
    browser.py
    session.py
    scheduler.py
    risk.py
    cli.py
    schema.sql
    tasks/
      healthcheck.py
      example_login_probe.py
  data/                         # gitignore
    xpage.db
    profiles/<account_id>/
    secrets/
    logs/
  docs/superpowers/specs/
    2026-07-15-browser-ops-runtime-design.md
```

### 2.3 Data model (SQLite)

**accounts**

| Column | Notes |
|--------|-------|
| id, name | |
| site_key | 站点逻辑名；策略与 allowlist 维度 |
| username | 登录标识 |
| secret_ref | 密钥引用；**默认不把明文密码写入 SQLite** |
| profile_path | `data/profiles/<id>` |
| proxy_id | 可空→默认代理策略 |
| status | `active` / `disabled` / `cooling` / `need_relogin` |
| last_ok_at, last_error | |
| meta_json | 扩展 |

**proxies**

| Column | Notes |
|--------|-------|
| id, name, scheme, host, port | scheme: `socks5` / `http` |
| auth_ref | 可选 |
| health | `unknown` / `ok` / `bad` |
| last_check_at | |

**tasks**

| Column | Notes |
|--------|-------|
| id, name, account_id | |
| script | 模块路径，如 `runtime.tasks.healthcheck` |
| schedule | P0：**仅 interval**，如 `interval:300`（秒） |
| enabled | |
| max_retries, timeout_sec | |
| params_json | |

**task_runs**

| Column | Notes |
|--------|-------|
| id, task_id, started_at, finished_at | |
| status | `running` / `ok` / `fail` / `skipped_circuit` |
| error, log_path | |

**site_policies**

| Column | Notes |
|--------|-------|
| site_key | PK |
| url_allow_prefix | JSON 字符串数组 |
| min_interval_sec | 同账号最小间隔 |
| max_concurrency | 同站点并发，默认 1 |

### 2.4 Binding rules

```
Account 1─1 Profile directory
Account N─1 Proxy (proxy_id 可共享)
Account N─1 site_key
Task     N─1 Account
SitePolicy 1─1 site_key
```

- **P0 不做「一账号多站」**（串 cookie 风险）。多站 = 多 account 行（可同 username，不同 `site_key` + 不同 profile）。
- **一站多账号** = 多 account 同行 `site_key`；靠并发与 `min_interval_sec` 错开。

### 2.5 BrowserRuntime contract

```
Input:  profile_dir, proxy_url, port, stealth: bool
Steps:
  1. Optional proxy health probe
  2. Acquire profile file lock
  3. spawn: google-chrome --headless=new --user-data-dir=... \
            --proxy-server=... --remote-debugging-port=... --no-sandbox --disable-gpu
  4. wait http://127.0.0.1:<port>/json/version
  5. Chromium(ChromiumOptions().set_address(...).headless(True))
     # 5.0.0b0 attach bug workaround — mandatory
  6. If stealth: inject stealth_min.js via CDP / addScriptToEvaluateOnNewDocument
  7. yield tab
  8. finally: browser quit + free port + release lock
     # NEVER rmtree operational profiles
```

- 运营 profile **禁止**当临时目录删除。
- 研究回归使用 **临时** profile，可删，且不得指向 `data/profiles/`。

Default network policy:

- 非 `site_key` 标记为 local-only 的账号：**必须**配置可用 proxy（对齐本机 IPv6/出网现状）。
- 默认代理示例与现研究一致：`socks5://127.0.0.1:2080`（可配置，不写死唯一全局）。

### 2.6 Risk module (P0 minimum)

| Mechanism | Behavior |
|-----------|----------|
| Global concurrency | Default 5 |
| Account cooling | Consecutive failures ≥ k → `cooling` until cooldown ends |
| Proxy circuit | Health bad → bound tasks `skipped_circuit` |
| Site throttle | Within `min_interval_sec`, skip same account |
| URL allowlist | Before navigate: prefix check; violation → fail + audit |
| Audit log | JSON lines: ts, account, proxy, task, url, result |

### 2.7 Task script interface

```python
def run(ctx) -> Result:
    # ctx.tab, ctx.account, ctx.params, ctx.logger
    ...

# Result fields:
#   ok: bool
#   need_relogin: bool = False
#   retryable: bool = False
#   message: str = ""
```

Built-in examples:

1. `healthcheck` — open allowlisted URL, assert title/selector.
2. `login_probe` — if logged-out marker, return `need_relogin=True`.

**P0 login policy:** 人在环首次登录（`session login`）写入 profile；任务以 **复用会话** 为主。自动填表登录 **可选**，不作为 MVP 必达（避免验证码范围膨胀）。

### 2.8 Explicit non-goals (P0)

- 分布式、Web UI、多浏览器引擎抽象
- 同一 profile 多站
- 完整密码保险库产品
- 宣称绕过 Cloudflare 等第三方
- Xvfb / headed 模式

---

## 3. Flows, errors, acceptance

### 3.1 Flows

**Register (once)**

1. `proxy add` / `account add` / `policy set` / `task add`
2. Optional: `session login <account>` — human completes login, profile persisted

**Scheduler tick**

1. Select due enabled tasks
2. Risk checks: global concurrency, account status, proxy health, min_interval
3. Fail checks → `task_runs.skipped_circuit`
4. Else → lock profile → Runtime.start → `script.run` → update store/audit → Runtime.stop

**Session reuse**

- Same `account_id` → same `user-data-dir` → Chrome persists cookies

**Research regress**

- Temporary profile only; never mutates `data/profiles/`

### 3.2 Error matrix

| Case | Handling |
|------|----------|
| `ok=True` | run ok; clear failure streak; `last_ok_at` |
| `retryable=True` | backoff retry up to `max_retries` |
| `need_relogin=True` | fail run; set account `need_relogin`; later tasks may skip until human fix; **no** login storm |
| Proxy down | proxy `bad`; skip bound tasks; re-probe after cooldown |
| Profile lock busy | `skipped_circuit` |
| Chrome/attach fail | cleanup port; retryable; streak → account cooling |
| Allowlist violation | hard fail + `policy_violation` audit; do not mark proxy bad |
| Captcha / block page (own site) | fail, non-retryable optional cool-down; screenshot under `data/logs/` |

**Principle:** Failures **narrow blast radius** (one account / one proxy), never cascade to all browsers.

### 3.3 Concurrency and resources

| Item | P0 default |
|------|------------|
| Global browser concurrency | 5 |
| Same account | 1 (profile lock) |
| Same site_key | `max_concurrency` default 1 |
| Debug ports | Pool e.g. 9600–9699 |
| Profiles | Persist; no auto-delete |
| Logs | Per-run under `data/logs/`; simple retention cap allowed |

### 3.4 Secrets

- Passwords / proxy auth via `secret_ref` → `data/secrets/<name>` or env; files mode `0600`
- `data/` gitignored
- CLI must not echo secrets
- Audit: no passwords; full URL logged in P0 with documented warning (token redaction can be P1)

### 3.5 CLI surface

```text
python -m runtime doctor
python -m runtime proxy add|list|check
python -m runtime account add|list|status
python -m runtime policy set|show
python -m runtime task add|list|enable|disable
python -m runtime session login <account>
python -m runtime run --once <task>
python -m runtime run --loop
python -m runtime status
python -m runtime regress detect|monitor
```

### 3.6 Acceptance tests (P0 done)

| ID | Scenario | Pass criteria |
|----|----------|---------------|
| V1 | doctor | Chrome, DP 5.x attach path, proxy reachability → clear ok/fail |
| V2 | dual account isolation | two accounts write distinct localStorage marks; no cross-read |
| V3 | session persistence | after `session login`, `run --once` still authenticated (mock/own page) |
| V4 | dual proxy | two accounts different proxies; egress identity differs |
| V5 | schedule | interval task ≥10 successes; no port/profile clash |
| V6 | circuit | bad proxy → skip; other accounts still run |
| V7 | allowlist | non-prefix URL → fail + audit; no successful off-policy navigation |
| V8 | regress | `regress detect` does not touch `data/profiles`; hardened UA baseline not regressed |

Testing strategy:

- Unit: risk, allowlist, store CRUD (no browser)
- Integration: V2–V7 on machine with Chrome + proxy
- No mandatory CI layer unless later requested

### 3.7 Locked default decisions (no TBD)

| Topic | Default |
|-------|---------|
| 5.0.0b0 attach bug | Always `ChromiumOptions.headless(True)` attach path |
| Egress / IPv6 | Prefer mandatory proxy for non-local site_keys |
| Auto-login / captcha | Human-in-the-loop first login for P0 |
| Code dedup with antibot | Extract shared launch into BrowserRuntime; antibot becomes caller or thin wrapper |
| Scope creep | No Web UI / distributed / multi-engine in P0 |
| Headed / Xvfb | Out of scope; document as environment limit |
| Cloudflare bypass claims | Forbidden in docs and success metrics |

### 3.8 Prior research status (context only)

Existing antibot work remains valid as the **fingerprint / monitor lab**:

- Baseline / hardened sannysoft results, takeover pattern, `stealth_min.js`, BotMonitor page alerts — **inputs** to Runtime defaults.
- Unclosed items (httpbin status listen root-cause, upstream issue filing) are **not P0 blockers**; track as optional research backlog, not product launch gates.

---

## 4. Implementation notes for planning (not implementation)

Suggested implementation order after plan approval:

1. `data/` layout + `schema.sql` + `store.py`
2. `browser.py` Runtime extracted from takeover pattern
3. `risk.py` + `session.py` locks
4. CLI: doctor / account / proxy / policy
5. `session login` + one healthcheck task
6. `run --once` then `run --loop`
7. Wire `regress` to existing antibot
8. Acceptance V1–V8 scripts or checklist

---

## 5. Spec self-review

| Check | Result |
|-------|--------|
| Placeholders / TBD | None left as open product decisions; P1 items explicitly deferred |
| Internal consistency | Profile 1:1 account; proxy on account; interval-only schedule; human login — aligned across sections |
| Scope | Single phase P0; multi-machine/UI deferred |
| Ambiguity | 「过检测」defined as stability + lab observability, not third-party bypass |
| Git commit | **Skipped:** workspace is not a git repository; file written on disk only |

---

## 6. Approval

- Brainstorming sections 1–3: **user approved** (2026-07-15)
- Written spec: **awaiting user review of this file**

After approval of this file, next step is **writing-plans** skill to produce the P0 implementation plan (not code yet).
