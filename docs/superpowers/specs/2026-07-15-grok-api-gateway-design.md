# Design: Grok API 网关（grokgw）

- **Date:** 2026-07-15
- **Status:** Draft for user review (brainstorming: 方案 A 已选, 设计第 1 节已口头确认)
- **Repo:** `xpage` 研究仓, 新建 `grokgw/` 子目录
- **Phase covered:** M0-M2 (单机 headless 封装); M3+ 为演进预留

---

## 1. Product positioning

### 1.1 One-liner

把已安装的 **Grok Build CLI**（`grok -p`）封装成本地 **OpenAI 兼容 API 服务**，复用 SuperGrok 订阅认证（`~/.grok/auth.json`），无需 xAI API key，供单机/小团队自用。

### 1.2 为什么选 headless 封装路线

| 路线 | 决策 | 理由 |
|------|------|------|
| **A. headless 封装（选定）** | ✅ | 官方支持路径（README "Building with Grok" 章节直接给了示例）；复用 SuperGrok 订阅；CLI 自管 token 刷新；隐私可控（隔离空目录规避仓库上传）；本机 grok 0.2.101 + auth.json 已就绪 |
| B. OAuth 直连代理 | ✗ | SuperGrok 标准订阅直连 `api.x.ai/v1` 可能 403（Hermes issue #26847 实证）；需自行管理 token 刷新与 header 构造 |
| C. 双路兜底 | ✗ | 复杂度最高，M0 不值得 |
| D. 逆向 grok.com web 端 | ✗ | 不必要——已有官方 CLI + 订阅；反爬对抗非本需求目标 |

### 1.3 Constraints

| Decision | Choice |
|----------|--------|
| 使用场景 | 单机自用 / 小团队（1-5 并发） |
| 认证来源 | SuperGrok 订阅的 `~/.grok/auth.json`（CLI 自动管理刷新） |
| 模型 | `grok-4.5`（config.toml 已设为默认）, `grok-build` |
| API 格式 | OpenAI Chat Completions 兼容（`/v1/chat/completions`） |
| 流式 | SSE（Server-Sent Events） |
| 多轮会话 | M0 无状态（messages 拼接为 prompt）；M2 可选 `-s session-id` 有状态 |
| function calling | **不支持**（Grok Build headless 的 `--tools` 是内置工具 allowlist，不接 OpenAI function schema） |
| 性能定位 | 低并发自用，非高并发生产（每请求 spawn `grok` 进程，cold start ~2-5s） |

### 1.4 关键风险与诚实标注

| 风险 | 说明 | 缓解 |
|------|------|------|
| **仓库上传隐私** | 有逆向分析（gist: hondrytravis）实证 Grok Build 在仓库目录运行时，会把整个仓库（含未读文件 + git history）作为 git bundle 上传到 GCS `grok-code-session-traces`，且 "Improve the model" 开关无效 | `--cwd` 指向 `/tmp/grokgw-sandbox-*` 空隔离目录，请求不接触用户真实仓库 |
| **auth 7 天过期** | SuperGrok browser login 的 token 7 天后过期 | 服务检测到 auth 失败（401/CLI 报错）时返回明确错误 JSON，提示运行 `grok login` |
| **CLI 版本变动** | `grok` CLI 仍在 beta（0.2.101），`streaming-json` schema 可能变 | `grok_runner.py` 做防御性解析（未知 `type` 跳过而非崩溃）；spec 记录当前 schema |
| **进程开销** | 每请求 spawn `grok` 进程 | 信号量限并发（默认 3）；M3 可演进为 inference proxy 直连 |

---

## 2. Architecture

### 2.1 数据流总览

```
OpenAI SDK / curl / agent client
        │
        ▼
  FastAPI (grokgw server)
  POST /v1/chat/completions
  GET  /v1/models
  GET  /healthz
        │
        ▼
  mapping.to_cli_args(req)
    - 拼 prompt（messages -> 单字符串）
    - 映射 model / reasoning_effort -> CLI flags
        │
        ▼
  sandbox.create()  →  /tmp/grokgw-sandbox-<uuid>/（空目录）
        │
        ▼
  grok_runner.run / run_stream
    asyncio.create_subprocess_exec(
      "grok", "--no-auto-update",
      "-p", <prompt>,
      "-m", <model>,
      "--cwd", <sandbox_dir>,
      "--output-format", "streaming-json" | "json",
      "--disallowed-tools", "Agent,run_terminal_cmd,search_replace",
      "--no-memory",
      ["--reasoning-effort", <level>]  # 若指定
    )
        │
        ▼
  解析 stdout NDJSON 事件
    "text"   →  delta.content
    "thought"→  delta.reasoning_content（可选透传）
    "end"    →  finish_reason: stop
    "error"  →  error chunk
        │
        ▼
  mapping.to_openai_response / to_sse_chunk
        │
        ▼
  返回 OpenAI 兼容 JSON / SSE stream
        │
        ▼
  sandbox.cleanup()  →  rmtree(sandbox_dir)
```

### 2.2 认证流

```
服务进程以用户身份运行（HOME = /home/zakza）
  → grok CLI 启动时读 ~/.grok/auth.json
  → token 过期时 CLI 自动用 refresh_token 刷新（CLI 内部行为，对服务透明）
  → 若 refresh_token 也过期（7天+未登录）→ CLI 返回 auth 错误
  → 服务捕获错误，返回 HTTP 401 + {"error":{"message":"Grok auth expired. Run: grok login"}}
```

---

## 3. Components

### 3.1 目录结构

```
grokgw/
├── grokgw/
│   ├── __init__.py
│   ├── __main__.py        # python -m grokgw 入口 → uvicorn.run(server.app)
│   ├── config.py          # 配置：端口/并发/sandbox 目录/API key/grok 路径
│   ├── server.py          # FastAPI app + 路由定义
│   ├── grok_runner.py     # spawn grok 子进程、解析 streaming-json
│   ├── mapping.py          # OpenAI Request ↔ grok CLI args 互转
│   ├── sandbox.py          # 隔离空目录管理（mkdtemp / rmtree）
│   └── models.py           # Pydantic 模型（OpenAI 兼容 schema）
├── tests/
│   ├── test_mapping.py     # 映射逻辑单测（无需 grok 进程）
│   ├── test_grok_runner.py  # runner 解析单测（mock subprocess / 真实 grok 冒烟）
│   ├── test_server.py       # API 端点单测（mock runner）
│   └── conftest.py
├── pyproject.toml
└── README.md
```

### 3.2 模块职责

| 模块 | 职责 | 依赖 | 可独立测试 |
|------|------|------|------------|
| `config.py` | 读环境变量/默认值：`GROKGW_PORT`(8787)、`GROKGW_MAX_CONCURRENT`(3)、`GROKGW_SANDBOX_ROOT`(`/tmp`)、`GROKGW_API_KEY`(可选)、`GROKGW_GROK_BIN`(`grok` 或绝对路径)、`GROKGW_TIMEOUT`(120,秒)、`GROKGW_EXPOSE_REASONING`(false,是否透传 thought 事件为 `reasoning_content`) | 无 | ✅ 纯函数 |
| `models.py` | Pydantic 模型：`ChatCompletionRequest`、`ChatCompletionResponse`、`ChatCompletionChunk`、`ModelList`；严格类型，无 `Any` | 无 | ✅ 纯数据 |
| `mapping.py` | `to_cli_args(req) -> list[str]`（拼 prompt + flags）；`to_openai_response(json_output, req) -> dict`；`to_sse_chunk(event) -> str | None` | models | ✅ 纯映射 |
| `sandbox.py` | `create() -> str`（mkdtemp 返回空目录路径）；`cleanup(path)`（rmtree） | config | ✅ 文件系统 |
| `grok_runner.py` | `async run(args) -> dict`（非流式，读全部 stdout → json）；`async run_stream(args) -> AsyncGenerator[event]`（流式，逐行 yield）；超时/退出码处理 | sandbox, config | ✅ mock subprocess |
| `server.py` | FastAPI app；路由 `POST /v1/chat/completions`、`GET /v1/models`、`GET /healthz`；信号量限并发；可选 API key 认证中间件 | grok_runner, mapping, models, config | ✅ mock runner |

### 3.3 接口定义

#### `POST /v1/chat/completions`

请求（OpenAI 标准 schema 子集）：
```json
{
  "model": "grok-4.5",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 4096,
  "reasoning_effort": "medium"
}
```

支持的 `model` 值：`grok-4.5`、`grok-build`、`grok-latest`（→ `grok-4.5`）。

响应（stream=false）— 标准 `ChatCompletion`：
```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion",
  "created": 1721000000,
  "model": "grok-4.5",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello! How can I help?"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
}
```

响应（stream=true）— SSE：
```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":1721000000,"model":"grok-4.5","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":1721000000,"model":"grok-4.5","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":1721000000,"model":"grok-4.5","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

#### `GET /v1/models`
```json
{
  "object": "list",
  "data": [
    {"id": "grok-4.5", "object": "model", "created": 1721000000, "owned_by": "xai"},
    {"id": "grok-build", "object": "model", "created": 1721000000, "owned_by": "xai"},
    {"id": "grok-latest", "object": "model", "created": 1721000000, "owned_by": "xai"}
  ]
}
```

#### `GET /healthz`
```json
{"status": "ok", "grok_binary": "/home/zakza/.local/bin/grok", "grok_version": "0.2.101"}
```

---

## 4. Mapping logic

### 4.1 OpenAI Request → grok CLI args

```
to_cli_args(req: ChatCompletionRequest) -> list[str]:

  # 1. 拼 prompt
  if len(req.messages) == 1 and req.messages[0].role == "user":
      prompt = req.messages[0].content
  else:
      # system 前置,其余 "role: content" 格式拼接（官方示例做法）
      prompt = "\n".join(
          f"{m.role}: {m.content}" for m in req.messages
      )

  # 2. 模型映射
  model = {"grok-latest": "grok-4.5"}.get(req.model, req.model)

  # 3. CLI args
  args = [
      grok_bin,              # "grok" 或绝对路径
      "--no-auto-update",
      "-p", prompt,
      "-m", model,
      "--cwd", sandbox_dir,  # 隔离空目录
      "--output-format", "streaming-json" if req.stream else "json",
      "--disallowed-tools", "Agent,run_terminal_cmd,search_replace",
      "--no-memory",
  ]

  # 4. 可选 flags
  if req.reasoning_effort:
      args += ["--reasoning-effort", req.reasoning_effort]
      # 映射: openai "low"|"medium"|"high" -> grok "low"|"medium"|"high"
      # (grok 还支持 none|minimal|xhigh|max,但 OpenAI 标准只有三档)

  return args
```

**不传递的参数**：`temperature`、`max_tokens`、`top_p` — Grok Build CLI headless 无对应 flag。这些值被接受但不转发（避免 400）。spec 明确标注此行为。

### 4.2 grok streaming-json → OpenAI SSE

官方 `streaming-json` schema（grok 0.2.101，来自 README "Output Formats"）：
```json
{"type":"text","data":"Here's"}
{"type":"thought","data":"Analyzing the directory structure..."}
{"type":"end","stopReason":"EndTurn","sessionId":"abc123","requestId":"xyz789"}
```

映射：
```
to_sse_chunk(event: dict, req_id: str, model: str) -> str | None:

  etype = event.get("type")

  if etype == "text":
      return sse_format({
          "id": req_id, "object": "chat.completion.chunk",
          "created": now(), "model": model,
          "choices": [{"index": 0, "delta": {"content": event["data"]}, "finish_reason": None}]
      })

  if etype == "thought" and config.expose_reasoning:
      return sse_format({
          ...,
          "choices": [{"index": 0, "delta": {"reasoning_content": event["data"]}, "finish_reason": None}]
      })

  if etype == "end":
      reason = event.get("stopReason", "EndTurn").lower()
      # EndTurn -> stop, ToolCalls -> tool_calls, Length -> length
      finish = {"endturn": "stop", "toolcalls": "tool_calls", "length": "length"}.get(reason, "stop")
      return sse_format({
          ...,
          "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]
      })

  if etype == "error":
      return sse_format({
          "error": {"message": event.get("message", "grok error"), "type": "upstream_error"}
      })

  return None  # 未知 type -> 跳过（防御性）
```

### 4.3 grok json（非流式）→ OpenAI Response

官方 `json` 输出：
```json
{
  "text": "Here's a summary of the codebase...",
  "stopReason": "EndTurn",
  "sessionId": "abc123",
  "requestId": "xyz789"
}
```

映射：
```
to_openai_response(data: dict, req: ChatCompletionRequest) -> dict:

  finish = {"endturn": "stop", "toolcalls": "tool_calls", "length": "length"}.get(
      data.get("stopReason", "EndTurn").lower(), "stop"
  )

  return {
      "id": f"chatcmpl-{uuid4().hex[:24]}",
      "object": "chat.completion",
      "created": int(time.time()),
      "model": req.model,
      "choices": [{
          "index": 0,
          "message": {"role": "assistant", "content": data.get("text", "")},
          "finish_reason": finish
      }],
      "usage": None  # grok json 输出不包含 token usage;标注为 null
  }
```

**注意**：grok 0.2.101 实测返回完整 `usage`（input_tokens/output_tokens/total_tokens），mapping 已透传为 OpenAI 的 prompt/completion/total_tokens。spec 原始假设"不含 token"已修正。

---

## 5. Error handling

| 场景 | 检测 | 响应 |
|------|------|------|
| grok 二进制不存在 | 启动时 `healthz` 检查 + 请求时 `FileNotFoundError` | HTTP 503 `{"error":{"message":"grok binary not found at <path>"}}` |
| auth 过期（token 7天+未刷新） | grok CLI 退出码非 0 + stderr 含 auth/login 错误 | HTTP 401 `{"error":{"message":"Grok auth expired. Run: grok login"}}` |
| 请求超时 | `asyncio.wait_for` 超过 `GROKGW_TIMEOUT`(默认 120s) | HTTP 504 `{"error":{"message":"Grok inference timeout"}}` + kill 子进程 |
| 并发上限 | 信号量 `acquire()` 等待超时 | HTTP 429 `{"error":{"message":"Server at capacity, retry later"}}` |
| grok CLI 返回 error 事件 | streaming-json `{"type":"error","message":"..."}` | SSE error chunk / HTTP 502 JSON |
| grok CLI 退出码非 0 | `proc.returncode != 0` | HTTP 502 `{"error":{"message":"grok exited with code <n>","stderr":"<last 500 chars>"}}` |
| 无效 model 值 | `req.model` 不在允许列表 | HTTP 400 `{"error":{"message":"model '<x>' not supported. Available: grok-4.5, grok-build"}}` |
| sandbox 创建失败 | `mkdtemp` 异常 | HTTP 500 `{"error":{"message":"sandbox creation failed"}}` |
| 客户端 API key 无效 | 中间件校验 `GROKGW_API_KEY` 不匹配 | HTTP 401 `{"error":{"message":"invalid API key"}}` |

**资源清理**：无论成功/失败/超时，`sandbox.cleanup()` 在 `finally` 块执行；超时时 `proc.kill()` + `proc.wait()` 确保子进程不泄漏。

---

## 6. Testing

### 6.1 单元测试（无需 grok 进程）

| 测试文件 | 覆盖 |
|----------|------|
| `test_mapping.py` | prompt 拼接（单条/多条/system+user）；model 别名映射；reasoning_effort 映射；`to_sse_chunk` 各 event type；`to_openai_response` stopReason 映射；未知 event type 跳过不崩 |
| `test_config.py` | 环境变量读取；默认值；API key 可选 |
| `test_sandbox.py` | create 返回存在的空目录；cleanup 后目录不存在 |

### 6.2 Runner 测试（mock subprocess）

| 测试 | 覆盖 |
|------|------|
| `test_grok_runner::test_run_parses_json` | mock stdout 返回 json → 正确提取 text/stopReason |
| `test_grok_runner::test_run_stream_yields_events` | mock stdout 返回多行 NDJSON → 逐事件 yield |
| `test_grok_runner::test_timeout_kills_process` | mock 永不退出的进程 → 超时后 kill |
| `test_grok_runner::test_nonzero_exit_raises` | mock returncode=1 → 抛异常含 stderr |

### 6.3 API 端点测试（mock runner）

| 测试 | 覆盖 |
|------|------|
| `test_server::test_chat_non_stream` | POST /v1/chat/completions stream=false → 200 + 正确 schema |
| `test_server::test_chat_stream` | POST stream=true → SSE 格式 + [DONE] 结束 |
| `test_server::test_models` | GET /v1/models → 列表正确 |
| `test_server::test_healthz` | GET /healthz → 200 + grok_binary |
| `test_server::test_concurrency_limit` | 并发超过 MAX_CONCURRENT → 429 |
| `test_server::test_invalid_model` | model="gpt-4" → 400 |
| `test_server::test_apikey_auth` | 设 GROKGW_API_KEY → 无 header 401；正确 header 200 |

### 6.4 冒烟测试（真实 grok，手动/CI 可选）

```bash
# 前提：grok 已登录（~/.grok/auth.json 存在）
python -m grokgw &
sleep 2

# 非流式
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Reply with exactly PONG"}]}' \
  | jq .choices[0].message.content
# 期望: "PONG"

# 流式
curl -sN http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Say hello"}],"stream":true}'
# 期望: SSE chunks + data: [DONE]
```

### 6.5 验收标准

| V# | 验收项 | 通过条件 |
|----|--------|----------|
| V1 | 非流式 chat | `curl POST /v1/chat/completions` 返回 200 + 正确 `choices[0].message.content` |
| V2 | 流式 chat | `curl -N POST stream=true` 返回 SSE + `data: [DONE]` 结束 |
| V3 | OpenAI SDK 兼容 | `from openai import OpenAI; client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="dummy")` 可正常调用 |
| V4 | models 端点 | `GET /v1/models` 返回 grok-4.5 + grok-build |
| V5 | healthz | `GET /healthz` 返回 grok 版本 |
| V6 | auth 过期提示 | 模拟 auth 失败 → 401 + 提示 `grok login` |
| V7 | 并发限制 | 超过 MAX_CONCURRENT → 429 |
| V8 | 隔离验证 | 请求期间 `ls /tmp/grokgw-sandbox-*` 为空目录；请求后目录已清理 |
| V9 | 单测全过 | `pytest grokgw/tests/` 全绿 |

---

## 7. Milestones

| Milestone | 范围 | 交付物 |
|-----------|------|--------|
| **M0: MVP** | config + models + mapping + sandbox + grok_runner + server 基础路由(非流式) | 可 `curl` 调用非流式 chat；V1/V4/V5/V9 通过 |
| **M1: 流式 + 认证** | 流式 SSE + reasoning 透传 + 可选 API key 认证 + 并发信号量 | V2/V3/V7/V8 通过 |
| **M2: 健壮性** | auth 过期检测 + 超时处理 + 全部错误码 + 有状态会话(`-s`)可选 | V6 + 全错误码覆盖 |
| **M3+（演进预留）** | inference proxy 直连（绕过 CLI 进程开销）；多账号 token 池；function calling 评估 | 不在本次 spec 范围 |

---

## 8. Evolution / Future work

### 8.1 inference proxy 直连（M3 候选）

官方 README 给了直接用 `auth.json` token 调 `cli-chat-proxy.grok.com` 的方法：
```bash
curl -N -X POST "https://cli-chat-proxy.grok.com/v1/chat/completions" \
  -H "Authorization: Bearer $(jq -r '."https://accounts.x.ai/sign-in".key' ~/.grok/auth.json)" \
  -H "X-XAI-Token-Auth: xai-grok-cli" \
  -H "x-grok-model-override: grok-build" \
  -d '{"model":"grok-build","messages":[...],"stream":true}'
```
绕过 CLI 进程开销，性能提升 10-50x。但需自行管理：token 刷新、header 构造、`x-grok-model-override` 路由。作为 M3 演进项。

### 8.2 多账号 token 池

若有多个 SuperGrok 账号，可做 token 轮换池（类似 `grok-bypass` 的 session multiplexing）。M4+。

### 8.3 function calling 评估

Grok Build headless 的 `--tools` 是内置工具 allowlist（`read_file`/`grep`/`bash` 等），不接受 OpenAI function schema。如需 function calling，应走官方 xAI API（`api.x.ai/v1`，需 `XAI_API_KEY`），不在 grokgw 范围内。

---

## 9. References

- Grok Build 官方文档（本地 `~/.grok/README.md`，grok 0.2.101）— "Building with Grok" 章节给了 headless 封装成 OpenAI-compatible 的 Python/TS 示例
- `docs.x.ai/build/overview` — Grok Build 概述
- `docs.x.ai/build/cli/headless-scripting` — headless flags 参考
- `docs.x.ai/developers/models/grok-4.5` — 模型规格（500K context, $2/$6 per M tokens）
- `docs.x.ai/build/enterprise` — 认证方式（browser OIDC / device code / API key / external auth）
- gist: hondrytravis — Grok Build wire-level analysis（仓库上传隐私风险实证）
- gist: daniel-farina — Grok CLI default system prompt（v0.1.211 提取）
- `superagent-ai/grok-cli` — 第三方 grok-cli 实现的 headless JSONL emitter（schema 参考）
- `0xHoneyJar/loa` PR #1057 — grok-headless adapter（验证此路径可行）
- `progrok` / `grok-oauth-proxy` / `grok-to-openai` — 相关开源封装项目
