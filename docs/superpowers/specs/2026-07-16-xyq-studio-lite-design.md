# Design: XYQ Studio Lite（xpage 轻量创作编排层）

- **Date:** 2026-07-16
- **Status:** **ROADMAPPED** — 设计仍有效；**尚未 scaffold `studio/`**。启动日另定；本周期非主线（见 `docs/ROADMAP.md`）。原批注：Approved for P0 implementation (option A)。
- **Repo:** `xpage`（`~/project/research/xpage`）
- **Package:** `studio/`
- **Phase covered:** Full pipeline design; **implementation scope of this pass = P0 only**

---

## 1. Product positioning

### 1.1 One-liner

在 **xpage** 内新建轻量 **创作编排层**：管理角色资产与项目状态，经人工确认剧本后，消费 **小云雀（XYQ）Access Key + xyq-skill OpenAPI** 生成分镜视频，下载到本地并通知；**不重造** xyq 的浏览器登录与 Playwright 栈。

### 1.2 Goals

| 阶段 | 能力 | 人工门 |
|------|------|--------|
| A. 会话/账号 | Key 加载与有效性检查；登录出钥仍在 xyq | 验证码/风控需人（不在 studio 主路径） |
| B. 角色资产 | 名称、描述、三视图、视频 agent 提示词 | 录入即可 |
| C. 创意 | 想法 → 自动剧本 | **你确认剧本** |
| D. 分镜 | 确认后 → 分镜视频提示词 | 可选再确认 |
| E. 生成 | XYQ API + 角色参考图 → 生视频 | — |
| F. 收尾 | 轮询 → 下载 → 通知 | — |
| G. 韧性 | 问题记录 + 有限自愈 | 不可自愈则停并告警 |

### 1.3 Non-goals (v1)

- 不嵌 Playwright / 不共用 `~/project/xyq/.xyq-auth/chrome-profile`
- 不做抖音/社媒自动发布
- 不把 `pippit-tool-cli short-drama` 全流程当主路径（可作 P4 适配器）
- 不在 studio 内实现 headed 浏览器登录（本机 headless 限制，见 AGENTS.md）
- 剧本未 `approve` **禁止**自动 `submit_run`（成本与风格硬门）

### 1.4 Constraints

| Decision | Choice |
|----------|--------|
| 落点 | `xpage/studio/`（Python，与 `runtime/` / `grokgw/` 并列） |
| 出 Key | `~/project/xyq`（`ensure-access-key`）；studio 只读 `XYQ_ACCESS_KEY` |
| 生视频主路径 | xyq-skill 图生视频会话（OpenAPI submit/get/upload） |
| 状态存储 v1 | 文件库 `data/studio/`（gitignore 已覆盖 `data/`） |
| LLM（P1+） | `grokgw` 或任意 OpenAI 兼容；无 LLM 时模板 fallback |
| 代理 | 与本机一致：`socks5://127.0.0.1:2080`（HTTP 客户端） |

**原则：** 复用 Key 与 API 行为契约，**不**复用浏览器实现栈。

---

## 2. Architecture

### 2.1 Logical components

```text
CLI (doctor/char/project/script/board/run)
        │
        ▼
   File Store (data/studio/)
        │
   ┌────┴────┬────────────┐
   ▼         ▼            ▼
 Characters  Projects   Runs/events
   │         │            │
   │    script/board   orchestrator
   │    (P1)           + heal (P3)
   │                      │
   └──────► xyq client (P2) ── OpenAPI ── XYQ
                      │
                   notify (P2)
```

| Component | Responsibility | Phase |
|-----------|----------------|-------|
| **CLI** | doctor / char / project / script / board / run | P0 起 |
| **paths + store** | `data/studio` 目录与 JSON CRUD | P0 |
| **key_loader** | 从 env / xyq `access-key.env` 加载 Key（不打印明文） | P0 |
| **script_writer / storyboard** | idea → 剧本 → 分镜 | P1 |
| **xyq client + poller** | upload / submit / poll / download（库化，可抛异常） | P2 |
| **orchestrator + heal + notify** | 状态机、有限自愈、完成通知 | P2–P3 |

### 2.2 Directory layout

```text
xpage/
  studio/
    __init__.py
    __main__.py
    cli.py
    paths.py
    models.py
    store.py
    auth/
      key_loader.py
    characters/          # P1+ 可拆；P0 CRUD 在 store
    creative/            # P1: script_writer, storyboard, prompt_pack
    xyq/                 # P2: client, poller
    pipeline/            # P2–P3: orchestrator, heal, notify
  data/studio/           # gitignore via data/
    characters/<id>/
      profile.json
      refs/              # 三视图副本
    projects/<pid>/
      meta.json
      idea.md
      script.md
      script_status.json
      storyboard.json    # P1+
      runs/              # P2+
      outputs/           # P2+
      events.jsonl       # P2+
  docs/superpowers/specs/
    2026-07-16-xyq-studio-lite-design.md
```

### 2.3 End-to-end state machine

```text
[ensure_key]  (xyq 仓 / 已有 env；studio doctor 校验)
    ↓
[char: upsert 角色 + 三视图]
    ↓
[project: new + idea]
    ↓
[script: generate] ──→ status=await_confirm ──→ 你 review
    ↓ approve / revise
[storyboard: generate prompts]  （可选 await_board_confirm）
    ↓
[upload refs]  三视图 → asset_ids（落盘复用）
    ↓
[submit_run]  message=分镜提示词包 + agent 角色提示
    ↓
[poll]  10s；needs_input → 记日志并 pause（默认不自动瞎答）
    ↓
[download] → data/studio/projects/<pid>/outputs/
    ↓
[notify] + [events audit]
```

**Run 状态**（写入 `runs/<run_id>.json`，P2+）：

`prepared → submitted → running → needs_input | succeeded → downloading → done`

失败侧：`retryable_fail → healing → …` 或 `failed_needs_human`

**硬门：** `script_status != approved` 时，`run start` / `submit_run` **必须拒绝**。

---

## 3. Data model (minimal)

### 3.1 Character — `data/studio/characters/<id>/profile.json`

```json
{
  "id": "xiao_mao",
  "name": "小毛",
  "description": "...",
  "views": {
    "front": "refs/front.png",
    "side": "refs/side.png",
    "back": "refs/back.png"
  },
  "agent_prompt": "角色一致性约束与镜头风格……",
  "xyq_asset_ids": {
    "front": null,
    "side": null,
    "back": null
  },
  "created_at": "2026-07-16T12:00:00",
  "updated_at": "2026-07-16T12:00:00"
}
```

- `views.*` 相对角色目录；P0 在 `char add` 时把源文件复制到 `refs/`。
- `xyq_asset_ids` 在 P2 upload 后回填；P0 保持 `null`。

### 3.2 Project — `data/studio/projects/<pid>/`

| File | Purpose | P0 |
|------|---------|----|
| `meta.json` | id, title, cast[], created_at, updated_at | Yes |
| `idea.md` | 创意原文 | Yes |
| `script.md` | 剧本正文 | skeleton empty |
| `script_status.json` | `{ "status": "draft" \| "await_confirm" \| "approved" }` | Yes (`draft`) |
| `storyboard.json` | shots[] | P1 |
| `runs/<run_id>.json` | 运行状态 | P2 |
| `outputs/*.mp4` | 成片 | P2 |
| `events.jsonl` | 问题与自愈轨迹 | P2–P3 |

### 3.3 Account layer

- **v1 (P0):** 只管理 Key 来源与是否已配置（`studio doctor`）；不存明文到 studio 数据目录。
- **v1.1:** 可选多 key 路径 / 冷却 / `need_relogin` 元数据；**仍不**在 studio 重做浏览器登录。

---

## 4. Integration map

| 能力 | 来源 | studio 怎么用 |
|------|------|----------------|
| 出 Key / 浏览器登录 | `~/project/xyq` | 文档 + 可选子进程 `ensure-access-key`；失败 → `need_relogin` + 通知 |
| OpenAPI 生视频 | `~/.agents/skills/xyq-skill/scripts/` | P2：`client.py` 库化（**禁止** skill 式 `sys.exit` 硬退） |
| 剧本/分镜 LLM | xpage `grokgw` 或 OpenAI 兼容 | `OPENAI_BASE_URL` + model；无则模板 |
| 审计风格 | `runtime.audit` / `Result.retryable` 语义 | 对齐语义，不绑 BrowserRuntime |
| 代理 | `127.0.0.1:2080` | P2 HTTP 客户端走代理 |

Key 解析顺序（`key_loader`）：

1. 环境变量 `XYQ_ACCESS_KEY`
2. 环境变量 `XYQ_ACCESS_KEY_FILE` 指向的文件
3. 默认路径 `$XYQ_ROOT/.xyq-auth/access-key.env`（`XYQ_ROOT` 默认 `~/project/xyq`）
4. 解析 `export XYQ_ACCESS_KEY=...` 或 `KEY=value` 行

---

## 5. Self-heal policy (P3; design now)

| 错误类 | 例子 | 动作 |
|--------|------|------|
| 瞬时网络 / 5xx / 超时 | URLError、502 | 指数退避，最多 N 次 |
| 限流 | 429 | 拉长间隔，尊重最小 10s |
| 鉴权失效 | 401、key 无效 | 尝试一次 ensure-key；仍失败 → **停 + 通知** |
| 平台追问 | needs_input | **默认 pause**，记 events |
| 上传失败 | 单图失败 | 换图重试 / 跳过该视角并告警 |
| 下载失败 | URL 过期 | 重新 get_thread 抽 URL 再下 |
| Captcha / 风控 | captcha、人机 | **禁止自动重试** |

每次 heal 写 `events.jsonl`：`{ts, run_id, stage, error, action, attempt, result}`。

---

## 6. CLI surface

```bash
source antibot/.venv/bin/activate
# Key：export XYQ_ACCESS_KEY=...  或依赖 xyq .xyq-auth/access-key.env

python -m studio doctor

python -m studio char add --id xiao_mao --name 小毛 --desc '...' \
  --front f.png --side s.png --back b.png \
  --agent-prompt '...'   # 或 --agent-prompt-file path
python -m studio char list
python -m studio char show xiao_mao
python -m studio char update xiao_mao --desc '...'
python -m studio char remove xiao_mao

python -m studio project new --id demo --idea '厨房追逐喜剧 15 秒' --cast xiao_mao
python -m studio project list
python -m studio project show demo

# P1+
# python -m studio script gen --project demo
# python -m studio script approve --project demo
# python -m studio board gen --project demo
# python -m studio run start --project demo
# python -m studio run status --project demo
```

P0 对未实现子命令应打印清晰错误并 exit 非 0（不静默成功）。

---

## 7. Phasing & acceptance

| Phase | Scope | Acceptance |
|-------|-------|------------|
| **P0** | doctor + key 加载 + char CRUD + 空 project 骨架 | 不调 API 也能管角色/项目；doctor 报 Key/数据目录状态 |
| **P1** | script gen/approve + board gen（LLM 或模板） | 能审剧本再出分镜 JSON |
| **P2** | xyq client + upload + submit/poll/download + notify | 一条 idea 出本地 mp4（且需 script approved） |
| **P3** | heal 分类、events、有限自愈、多 run 历史 | 假 429 可恢复；401/captcha 停并通知 |
| **P4** | short-drama 适配器 / 多 key 池 / headed 登录 task | 仅产品确认后 |

### 7.1 P0 success criteria (this implementation)

1. `python -m studio doctor` 输出可解析的 OK/FAIL（数据目录、Key 是否配置；不泄露 Key 明文）。
2. `char add` 写入 `profile.json` 并复制三视图到 `refs/`；`list` / `show` 可读回。
3. `project new` 创建骨架文件且 `script_status=draft`；`list` / `show` 可用。
4. 不发起任何 XYQ 网络请求。
5. `AGENTS.md` 有 studio 入口说明。

---

## 8. Risks & deliberate trade-offs

1. **Headless 限制：** 浏览器登录不进 studio 主路径；出 Key 在 xyq 有显示/ headed 环境完成。
2. **剧本质量依赖 LLM：** P1 必须有模板 fallback。
3. **硬门：** 未 approve 不 `submit_run`。
4. **skill 脚本 `sys.exit`：** P2 库化 client 必须可抛异常，否则 orchestrator 无法自愈。
5. **双状态机风险：** v1 只认 skill 图生视频主路径。

---

## 9. Implementation note (current pass)

- **In scope:** this design document + P0 scaffold (`studio/` doctor/char/project + `data/studio`).
- **Out of scope until explicit request:** P1 script/board, P2 xyq client pipeline, P3 heal.
