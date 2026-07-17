# Grok API Gateway (grokgw) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Progress snapshot (2026-07-17)

| 项 | 状态 |
|----|------|
| M0–M2 本地网关 + proxy 后端 + 单测 | **DONE**（`grokgw/` 在仓；pytest **80 passed**） |
| Media Phase1 | **DONE**（见 media plan snapshot） |
| BLR 远程 proxy 部署 | **ACTIVE** → `2026-07-17-grokgw-blr-proxy-deploy.md` |

历史 checkbox 未逐条回写；**以本表与 `docs/STATUS.md` 为准**。

**Goal:** 把已安装的 Grok Build CLI(`grok -p`)封装成本地 OpenAI 兼容 API 服务,复用 SuperGrok 订阅认证,供单机自用。

**Architecture:** Python 3.12 + FastAPI/uvicorn 异步单体。每请求 spawn `grok -p --output-format streaming-json` 子进程(在隔离空目录运行,规避仓库上传隐私风险),解析 NDJSON 事件回填 OpenAI Chat Completions 格式(流式 SSE + 非流式 JSON)。模块化拆分:config/models/mapping/sandbox/grok_runner/server,各可独立测试。

**Tech Stack:** Python 3.12、FastAPI、uvicorn、Pydantic v2、pytest、pytest-asyncio、httpx(TestClient)。本机 `grok 0.2.101`(已装 + SuperGrok 已登录)。

**Spec:** `docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`

**Notes for agents:**
- 工作区是 git 仓库(main 分支,3 commits)。Commit 步骤正常执行。
- 激活 venv:`source antibot/.venv/bin/activate`(已有 Python 3.12);或为 grokgw 建独立 venv。计划采用 **复用 `antibot/.venv`** + 在仓库根 `pip install -e ./grokgw`(editable)。
- `grok` 二进制在 `/home/zakza/.local/bin/grok`(已在 PATH),`~/.grok/auth.json` 存在(SuperGrok 已登录)。
- 单元测试不启 grok 进程(mock subprocess);冒烟测试手动/CI 可选(需真实 grok 登录)。
- 不要引入 function calling、多账号 token 池、inference proxy 直连(spec 标注为 M3+ 演进)。

---

## File map (create / modify)

| Path | Responsibility |
|------|----------------|
| `grokgw/pyproject.toml` | 包元数据 + 依赖(fastapi/uvicorn/pydantic) + dev 依赖(pytest/pytest-asyncio/httpx) |
| `grokgw/grokgw/__init__.py` | 包标记;`__version__ = "0.1.0"` |
| `grokgw/grokgw/__main__.py` | `python -m grokgw` 入口 -> uvicorn.run |
| `grokgw/grokgw/config.py` | 读环境变量;`Settings` dataclass |
| `grokgw/grokgw/models.py` | Pydantic 模型:ChatCompletionRequest/Response/Chunk,ModelList |
| `grokgw/grokgw/mapping.py` | `to_cli_args` / `to_openai_response` / `to_sse_chunk` 纯映射 |
| `grokgw/grokgw/sandbox.py` | `create()` / `cleanup(path)` 隔离空目录 |
| `grokgw/grokgw/grok_runner.py` | `async run()` / `async run_stream()`;spawn + 解析 + 超时/退出码 |
| `grokgw/grokgw/server.py` | FastAPI app + 路由 + 信号量 + 可选 API key 中间件 |
| `grokgw/tests/__init__.py` | 测试包标记 |
| `grokgw/tests/conftest.py` | 共享 fixtures(mock settings, mock subprocess) |
| `grokgw/tests/test_config.py` | config 单测 |
| `grokgw/tests/test_models.py` | 模型校验单测 |
| `grokgw/tests/test_mapping.py` | 映射逻辑单测(核心) |
| `grokgw/tests/test_sandbox.py` | sandbox 单测 |
| `grokgw/tests/test_grok_runner.py` | runner 单测(mock subprocess) |
| `grokgw/tests/test_server.py` | API 端点单测(mock runner) |
| `grokgw/README.md` | 使用说明 |
| `AGENTS.md` | 增加 grokgw 入口说明(Modify) |

---

### Task 1: Scaffold package, pyproject, config

**Files:**
- Create: `grokgw/pyproject.toml`
- Create: `grokgw/grokgw/__init__.py`
- Create: `grokgw/grokgw/config.py`
- Create: `grokgw/tests/__init__.py`
- Create: `grokgw/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`grokgw/tests/test_config.py`:
```python
import os
from grokgw.config import Settings


def test_defaults():
    s = Settings()
    assert s.port == 8787
    assert s.max_concurrent == 3
    assert s.sandbox_root == "/tmp"
    assert s.api_key is None
    assert s.grok_bin == "grok"
    assert s.timeout == 120
    assert s.expose_reasoning is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_PORT", "9999")
    monkeypatch.setenv("GROKGW_MAX_CONCURRENT", "10")
    monkeypatch.setenv("GROKGW_GROK_BIN", "/usr/local/bin/grok")
    monkeypatch.setenv("GROKGW_API_KEY", "secret")
    monkeypatch.setenv("GROKGW_TIMEOUT", "60")
    monkeypatch.setenv("GROKGW_EXPOSE_REASONING", "true")
    s = Settings.from_env()
    assert s.port == 9999
    assert s.max_concurrent == 10
    assert s.grok_bin == "/usr/local/bin/grok"
    assert s.api_key == "secret"
    assert s.timeout == 60
    assert s.expose_reasoning is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd grokgw && source ../antibot/.venv/bin/activate && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw'`

- [ ] **Step 3: Write pyproject.toml**

`grokgw/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "grokgw"
version = "0.1.0"
description = "OpenAI-compatible local API gateway wrapping Grok Build CLI"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
where = ["."]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: Write __init__.py and config.py**

`grokgw/grokgw/__init__.py`:
```python
__version__ = "0.1.0"
```

`grokgw/grokgw/config.py`:
```python
from __future__ import annotations
import os
from dataclasses import dataclass


def _get_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    port: int = 8787
    host: str = "127.0.0.1"
    max_concurrent: int = 3
    sandbox_root: str = "/tmp"
    api_key: str | None = None
    grok_bin: str = "grok"
    timeout: int = 120
    expose_reasoning: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            port=int(os.environ.get("GROKGW_PORT", "8787")),
            host=os.environ.get("GROKGW_HOST", "127.0.0.1"),
            max_concurrent=int(os.environ.get("GROKGW_MAX_CONCURRENT", "3")),
            sandbox_root=os.environ.get("GROKGW_SANDBOX_ROOT", "/tmp"),
            api_key=os.environ.get("GROKGW_API_KEY"),
            grok_bin=os.environ.get("GROKGW_GROK_BIN", "grok"),
            timeout=int(os.environ.get("GROKGW_TIMEOUT", "120")),
            expose_reasoning=_get_bool("GROKGW_EXPOSE_REASONING", False),
        )
```

- [ ] **Step 5: Install editable + run test**

Run: `cd /home/zakza/project/research/xpage && source antibot/.venv/bin/activate && pip install -e ./grokgw && pip install pytest pytest-asyncio httpx && python -m pytest grokgw/tests/test_config.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add grokgw/
git commit -m "feat(grokgw): scaffold package + config module with tests"
```

---

### Task 2: Pydantic models (OpenAI-compatible schema)

**Files:**
- Create: `grokgw/grokgw/models.py`
- Create: `grokgw/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`grokgw/tests/test_models.py`:
```python
import pytest
from pydantic import ValidationError
from grokgw.models import ChatCompletionRequest, Message


def test_request_minimal():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="Hello")],
    )
    assert req.model == "grok-4.5"
    assert req.stream is False
    assert req.temperature is None
    assert req.max_tokens is None
    assert req.reasoning_effort is None


def test_request_stream():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="Hi")],
        stream=True,
        reasoning_effort="high",
    )
    assert req.stream is True
    assert req.reasoning_effort == "high"


def test_request_system_user():
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ],
    )
    assert len(req.messages) == 2


def test_invalid_reasoning_effort():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="grok-4.5",
            messages=[Message(role="user", content="x")],
            reasoning_effort="invalid",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest grokgw/tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw.models'`

- [ ] **Step 3: Write models.py**

`grokgw/grokgw/models.py`:
```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None


class Delta(BaseModel):
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]


class ModelInfo(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str = "xai"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelInfo]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest grokgw/tests/test_models.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/models.py grokgw/tests/test_models.py
git commit -m "feat(grokgw): add Pydantic OpenAI-compatible models with validation tests"
```

---

### Task 3: Mapping logic (core - OpenAI <-> grok CLI args)

**Files:**
- Create: `grokgw/grokgw/mapping.py`
- Create: `grokgw/tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

`grokgw/tests/test_mapping.py`:
```python
import json
import pytest
from grokgw.config import Settings
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.models import ChatCompletionRequest, Message


def make_req(**kw):
    base = dict(model="grok-4.5", messages=[Message(role="user", content="Hi")])
    base.update(kw)
    return ChatCompletionRequest(**base)


# --- to_cli_args ---

def test_cli_args_single_user_message():
    req = make_req()
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    assert "grok" in args[0] or args[0] == "grok"
    assert "--no-auto-update" in args
    assert "-p" in args
    idx = args.index("-p")
    assert args[idx + 1] == "Hi"
    assert "-m" in args
    assert "grok-4.5" in args
    assert "--cwd" in args
    assert "/tmp/sbx" in args
    assert "--output-format" in args
    assert "json" in args  # non-stream default
    assert "--no-memory" in args
    assert "--disallowed-tools" in args
    assert "Agent,run_terminal_cmd,search_replace" in args


def test_cli_args_stream_uses_streaming_json():
    req = make_req(stream=True)
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    of_idx = args.index("--output-format")
    assert args[of_idx + 1] == "streaming-json"


def test_cli_args_multi_message_prompt():
    req = make_req(
        messages=[
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ]
    )
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    p_idx = args.index("-p")
    prompt = args[p_idx + 1]
    assert "system: Be concise." in prompt
    assert "user: Hello" in prompt


def test_cli_args_model_alias_grok_latest():
    req = make_req(model="grok-latest")
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    m_idx = args.index("-m")
    assert args[m_idx + 1] == "grok-4.5"


def test_cli_args_reasoning_effort():
    req = make_req(reasoning_effort="high")
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=Settings(), req_id="r1")
    re_idx = args.index("--reasoning-effort")
    assert args[re_idx + 1] == "high"


def test_cli_args_grok_bin_from_settings():
    s = Settings(grok_bin="/usr/local/bin/grok")
    req = make_req()
    args = to_cli_args(req, sandbox_dir="/tmp/sbx", settings=s, req_id="r1")
    assert args[0] == "/usr/local/bin/grok"


# --- to_openai_response ---

def test_to_openai_response_endturn():
    data = {"text": "Hello!", "stopReason": "EndTurn", "sessionId": "s1", "requestId": "q1"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "grok-4.5"
    assert resp["choices"][0]["message"]["content"] == "Hello!"
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert resp["id"].startswith("chatcmpl-")


def test_to_openai_response_length():
    data = {"text": "truncated", "stopReason": "Length"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["choices"][0]["finish_reason"] == "length"


def test_to_openai_response_usage_none():
    data = {"text": "x", "stopReason": "EndTurn"}
    req = make_req()
    resp = to_openai_response(data, req)
    assert resp["usage"] is None


# --- to_sse_chunk ---

def test_to_sse_chunk_text():
    ev = {"type": "text", "data": "Hello"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    assert chunk.startswith("data: ")
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["delta"]["content"] == "Hello"
    assert payload["choices"][0]["finish_reason"] is None


def test_to_sse_chunk_end():
    ev = {"type": "end", "stopReason": "EndTurn"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_to_sse_chunk_thought_hidden_by_default():
    ev = {"type": "thought", "data": "thinking..."}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is None  # expose_reasoning=False by default


def test_to_sse_chunk_thought_exposed():
    ev = {"type": "thought", "data": "thinking..."}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings(expose_reasoning=True))
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["choices"][0]["delta"]["reasoning_content"] == "thinking..."


def test_to_sse_chunk_error():
    ev = {"type": "error", "message": "boom"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is not None
    payload = json.loads(chunk[len("data: "):])
    assert payload["error"]["message"] == "boom"


def test_to_sse_chunk_unknown_type_skipped():
    ev = {"type": "unknown_future_event", "data": "x"}
    chunk = to_sse_chunk(ev, req_id="c1", model="grok-4.5", settings=Settings())
    assert chunk is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest grokgw/tests/test_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw.mapping'`

- [ ] **Step 3: Write mapping.py**

`grokgw/grokgw/mapping.py`:
```python
from __future__ import annotations
import json
import time
import uuid
from grokgw.config import Settings
from grokgw.models import ChatCompletionRequest

_MODEL_ALIASES = {"grok-latest": "grok-4.5"}
_FINISH_MAP = {"endturn": "stop", "toolcalls": "tool_calls", "length": "length"}


def _build_prompt(req: ChatCompletionRequest) -> str:
    if len(req.messages) == 1 and req.messages[0].role == "user":
        return req.messages[0].content
    return "\n".join(f"{m.role}: {m.content}" for m in req.messages)


def to_cli_args(
    req: ChatCompletionRequest, *, sandbox_dir: str, settings: Settings, req_id: str
) -> list[str]:
    prompt = _build_prompt(req)
    model = _MODEL_ALIASES.get(req.model, req.model)
    args = [
        settings.grok_bin,
        "--no-auto-update",
        "-p", prompt,
        "-m", model,
        "--cwd", sandbox_dir,
        "--output-format", "streaming-json" if req.stream else "json",
        "--disallowed-tools", "Agent,run_terminal_cmd,search_replace",
        "--no-memory",
    ]
    if req.reasoning_effort:
        args += ["--reasoning-effort", req.reasoning_effort]
    return args


def to_openai_response(data: dict, req: ChatCompletionRequest) -> dict:
    stop_raw = data.get("stopReason", "EndTurn")
    finish = _FINISH_MAP.get(stop_raw.lower(), "stop")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": data.get("text", "")},
            "finish_reason": finish,
        }],
        "usage": None,
    }


def to_sse_chunk(event: dict, *, req_id: str, model: str, settings: Settings) -> str | None:
    etype = event.get("type")

    if etype == "text":
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": event.get("data", "")}, "finish_reason": None}],
        }
    elif etype == "thought" and settings.expose_reasoning:
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"reasoning_content": event.get("data", "")}, "finish_reason": None}],
        }
    elif etype == "end":
        stop_raw = event.get("stopReason", "EndTurn")
        finish = _FINISH_MAP.get(stop_raw.lower(), "stop")
        payload = {
            "id": req_id, "object": "chat.completion.chunk", "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
        }
    elif etype == "error":
        payload = {
            "error": {"message": event.get("message", "grok error"), "type": "upstream_error"},
        }
    else:
        return None

    return f"data: {json.dumps(payload)}\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest grokgw/tests/test_mapping.py -v`
Expected: 13 PASS

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/mapping.py grokgw/tests/test_mapping.py
git commit -m "feat(grokgw): add OpenAI<->grok CLI mapping logic with full test coverage"
```

---

### Task 4: Sandbox isolation module

**Files:**
- Create: `grokgw/grokgw/sandbox.py`
- Create: `grokgw/tests/test_sandbox.py`

- [ ] **Step 1: Write the failing test**

`grokgw/tests/test_sandbox.py`:
```python
import os
import tempfile
from pathlib import Path
from grokgw.sandbox import create, cleanup


def test_create_returns_empty_dir():
    path = create()
    try:
        assert os.path.isdir(path)
        assert os.listdir(path) == []  # empty
        assert "grokgw-sandbox" in path
    finally:
        cleanup(path)


def test_cleanup_removes_dir():
    path = create()
    assert os.path.isdir(path)
    cleanup(path)
    assert not os.path.exists(path)


def test_cleanup_nonexistent_no_error():
    cleanup("/tmp/grokgw-nonexistent-xyz-12345")


def test_create_under_custom_root(tmp_path):
    # sandbox_root respected
    path = create(root=str(tmp_path))
    try:
        assert str(tmp_path) in path
    finally:
        cleanup(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest grokgw/tests/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw.sandbox'`

- [ ] **Step 3: Write sandbox.py**

`grokgw/grokgw/sandbox.py`:
```python
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path


def create(root: str | None = None) -> str:
    """Create an empty isolated directory for grok --cwd. Returns path."""
    prefix = "grokgw-sandbox-"
    path = tempfile.mkdtemp(prefix=prefix, dir=root)
    return path


def cleanup(path: str) -> None:
    """Remove the sandbox directory. No error if missing."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest grokgw/tests/test_sandbox.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/sandbox.py grokgw/tests/test_sandbox.py
git commit -m "feat(grokgw): add sandbox isolation (empty tmpdir per request)"
```

---

### Task 5: Grok runner (subprocess spawn + NDJSON parse)

**Files:**
- Create: `grokgw/grokgw/grok_runner.py`
- Create: `grokgw/tests/test_grok_runner.py`
- Create: `grokgw/tests/conftest.py`

- [ ] **Step 1: Write the failing test (mock subprocess)**

`grokgw/tests/conftest.py`:
```python
import asyncio
from typing import Iterable


class MockProc:
    """Mock asyncio subprocess for testing grok_runner."""
    def __init__(self, stdout_lines: list[bytes], returncode: int = 0, stderr: bytes = b""):
        self._stdout_lines = stdout_lines
        self._returncode = returncode
        self._stderr = stderr
        self._killed = False

    @property
    def returncode(self) -> int:
        return self._returncode

    @property
    def stdout(self):
        async def _aiter():
            for line in self._stdout_lines:
                yield line
        return _aiter()

    @property
    def stderr(self):
        return self._stderr

    async def wait(self) -> int:
        return self._returncode

    def kill(self):
        self._killed = True

    async def communicate(self):
        out = b"".join(self._stdout_lines)
        return out, self._stderr
```

`grokgw/tests/test_grok_runner.py`:
```python
import json
import pytest
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunner, GrokRunError
from tests.conftest import MockProc


@pytest.fixture
def runner(monkeypatch):
    r = GrokRunner(Settings())
    return r


async def test_run_parses_json_output(monkeypatch, runner):
    json_out = b'{"text":"Hello!","stopReason":"EndTurn","sessionId":"s1","requestId":"q1"}\n'
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    result = await runner.run(["grok", "-p", "Hi", "--output-format", "json"])
    assert result["text"] == "Hello!"
    assert result["stopReason"] == "EndTurn"


async def test_run_stream_yields_events(monkeypatch, runner):
    lines = [
        b'{"type":"text","data":"Hel"}\n',
        b'{"type":"text","data":"lo"}\n',
        b'{"type":"end","stopReason":"EndTurn"}\n',
    ]
    proc = MockProc(stdout_lines=lines, returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    events = []
    async for ev in runner.run_stream(["grok", "-p", "Hi", "--output-format", "streaming-json"]):
        events.append(ev)

    assert len(events) == 3
    assert events[0]["type"] == "text"
    assert events[0]["data"] == "Hel"
    assert events[2]["type"] == "end"


async def test_run_nonzero_exit_raises(monkeypatch, runner):
    proc = MockProc(stdout_lines=[], returncode=1, stderr=b"auth error: please login\n")

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(GrokRunError) as exc_info:
        await runner.run(["grok", "-p", "Hi"])
    assert "auth error" in str(exc_info.value)


async def test_run_timeout_kills_process(monkeypatch, runner):
    r = GrokRunner(Settings(timeout=1))  # 1 second timeout

    class HangingProc(MockProc):
        async def communicate(self):
            await asyncio.sleep(100)  # never returns
        async def wait(self):
            await asyncio.sleep(100)

    import asyncio
    proc = HangingProc(stdout_lines=[], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)

    with pytest.raises(TimeoutError):
        await r.run(["grok", "-p", "Hi"])
    assert proc._killed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest grokgw/tests/test_grok_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw.grok_runner'`

- [ ] **Step 3: Write grok_runner.py**

`grokgw/grokgw/grok_runner.py`:
```python
from __future__ import annotations
import asyncio
import json
from typing import AsyncIterator
from grokgw.config import Settings


class GrokRunError(Exception):
    """Raised when grok CLI exits non-zero."""
    def __init__(self, message: str, returncode: int, stderr: str):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class GrokRunner:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def run(self, args: list[str]) -> dict:
        """Run grok, read all stdout, parse final JSON. Raises GrokRunError/TimeoutError."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._settings.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"grok timed out after {self._settings.timeout}s") from None

        if proc.returncode != 0:
            stderr_str = stderr.decode(errors="replace") if stderr else ""
            raise GrokRunError(
                f"grok exited with code {proc.returncode}: {stderr_str[-500:]}",
                proc.returncode,
                stderr_str,
            )

        stdout_str = stdout.decode(errors="replace").strip()
        if not stdout_str:
            raise GrokRunError("grok produced no output", proc.returncode, "")
        return json.loads(stdout_str)

    async def run_stream(self, args: list[str]) -> AsyncIterator[dict]:
        """Run grok streaming-json, yield events. Raises GrokRunError on non-zero exit."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._settings.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"grok timed out after {self._settings.timeout}s") from None

            if proc.returncode != 0:
                stderr_data = await proc.stderr.read() if proc.stderr else b""
                stderr_str = stderr_data.decode(errors="replace")
                raise GrokRunError(
                    f"grok exited with code {proc.returncode}: {stderr_str[-500:]}",
                    proc.returncode,
                    stderr_str,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest grokgw/tests/test_grok_runner.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/grok_runner.py grokgw/tests/test_grok_runner.py grokgw/tests/conftest.py
git commit -m "feat(grokgw): add grok runner with subprocess spawn, NDJSON parse, timeout"
```

---

### Task 6: FastAPI server (non-stream endpoint + models + healthz)

**Files:**
- Create: `grokgw/grokgw/server.py`
- Create: `grokgw/tests/test_server.py`

- [ ] **Step 1: Write the failing test (mock runner)**

`grokgw/tests/test_server.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from grokgw.server import create_app


class FakeRunner:
    async def run(self, args):
        return {"text": "PONG", "stopReason": "EndTurn", "sessionId": "s1", "requestId": "q1"}

    async def run_stream(self, args):
        for ev in [
            {"type": "text", "data": "Hello"},
            {"type": "text", "data": " world"},
            {"type": "end", "stopReason": "EndTurn"},
        ]:
            yield ev


@pytest.fixture
def app():
    return create_app(runner=FakeRunner(), api_key=None, max_concurrent=3)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_chat_non_stream(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "ping"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "PONG"
    assert data["choices"][0]["finish_reason"] == "stop"


async def test_models_list(client):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    ids = [m["id"] for m in data["data"]]
    assert "grok-4.5" in ids
    assert "grok-build" in ids


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_invalid_model(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 400


async def test_invalid_request_body(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        # missing messages
    })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grokgw.server'`

- [ ] **Step 3: Write server.py (non-stream + models + healthz; stream/concurrency/auth in Task 7)**

`grokgw/grokgw/server.py`:
```python
from __future__ import annotations
import time
from typing import Protocol
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from grokgw.config import Settings
from grokgw.mapping import to_cli_args, to_openai_response, to_sse_chunk
from grokgw.models import ChatCompletionRequest, ModelInfo, ModelList
from grokgw.sandbox import create as create_sandbox, cleanup as cleanup_sandbox

_ALLOWED_MODELS = {"grok-4.5", "grok-build", "grok-latest"}


class RunnerProtocol(Protocol):
    async def run(self, args: list[str]) -> dict: ...
    async def run_stream(self, args: list[str]): ...


def create_app(*, runner: RunnerProtocol, api_key: str | None, max_concurrent: int) -> FastAPI:
    import asyncio
    settings = Settings.from_env()
    sem = asyncio.Semaphore(max_concurrent)

    app = FastAPI(title="grokgw")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "grok_binary": settings.grok_bin}

    @app.get("/v1/models")
    async def list_models():
        now = int(time.time())
        return ModelList(data=[
            ModelInfo(id="grok-4.5", created=now),
            ModelInfo(id="grok-build", created=now),
            ModelInfo(id="grok-latest", created=now),
        ])

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        if req.model not in _ALLOWED_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"model '{req.model}' not supported. Available: grok-4.5, grok-build, grok-latest",
            )

        async with sem:
            sandbox_dir = create_sandbox(root=settings.sandbox_root)
            req_id = f"chatcmpl-{__import__('uuid').uuid4().hex[:24]}"
            args = to_cli_args(req, sandbox_dir=sandbox_dir, settings=settings, req_id=req_id)
            try:
                if req.stream:
                    return StreamingResponse(
                        _stream_response(runner, args, req_id, req.model, settings, sandbox_dir),
                        media_type="text/event-stream",
                    )
                else:
                    data = await runner.run(args)
                    return to_openai_response(data, req)
            finally:
                if not req.stream:
                    cleanup_sandbox(sandbox_dir)

    async def _stream_response(runner, args, req_id, model, settings, sandbox_dir):
        try:
            async for event in runner.run_stream(args):
                chunk = to_sse_chunk(event, req_id=req_id, model=model, settings=settings)
                if chunk is not None:
                    yield chunk
            yield "data: [DONE]\n\n"
        finally:
            cleanup_sandbox(sandbox_dir)

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/server.py grokgw/tests/test_server.py
git commit -m "feat(grokgw): add FastAPI server with chat/models/healthz endpoints"
```

---

### Task 7: Streaming endpoint + API key auth + concurrency limit tests

**Files:**
- Modify: `grokgw/grokgw/server.py` (stream already added in Task 6; add auth middleware)
- Modify: `grokgw/tests/test_server.py`

- [ ] **Step 1: Add failing tests for streaming + auth + concurrency**

Append to `grokgw/tests/test_server.py`:
```python
async def test_chat_stream(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert resp.status_code == 200
    body = resp.text
    assert "data: " in body
    assert "Hello" in body
    assert "data: [DONE]" in body


@pytest.fixture
def authed_app():
    return create_app(runner=FakeRunner(), api_key="secret-key", max_concurrent=3)


@pytest.fixture
async def authed_client(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_missing_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 401


async def test_auth_wrong_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    }, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


async def test_auth_correct_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    }, headers={"Authorization": "Bearer secret-key"})
    assert resp.status_code == 200


async def test_healthz_no_auth_required(authed_client):
    """healthz should work even when API key is set (liveness probe)."""
    resp = await authed_client.get("/healthz")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests - stream passes, auth fails (not yet implemented)**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: `test_chat_stream` PASS (stream impl in Task 6); auth tests FAIL (no middleware yet)

- [ ] **Step 3: Add auth middleware to server.py**

In `grokgw/grokgw/server.py`, modify `create_app` to add middleware. Replace the `app = FastAPI(title="grokgw")` line block with:

```python
    app = FastAPI(title="grokgw")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # healthz and docs bypass auth (liveness/readiness)
        if request.url.path in ("/healthz", "/", "/docs", "/openapi.json"):
            return await call_next(request)
        if api_key is not None:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if token != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"message": "invalid API key", "type": "invalid_request_error"}},
                )
        return await call_next(request)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: 10 PASS (5 old + 5 new)

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/server.py grokgw/tests/test_server.py
git commit -m "feat(grokgw): add streaming SSE endpoint + optional API key auth middleware"
```

---

### Task 8: Entry point (__main__) + README

**Files:**
- Create: `grokgw/grokgw/__main__.py`
- Create: `grokgw/README.md`
- Modify: `AGENTS.md` (add grokgw section)

- [ ] **Step 1: Write __main__.py**

`grokgw/grokgw/__main__.py`:
```python
from __future__ import annotations
import uvicorn
from grokgw.config import Settings
from grokgw.grok_runner import GrokRunner
from grokgw.server import create_app


def main():
    settings = Settings.from_env()
    runner = GrokRunner(settings)
    app = create_app(
        runner=runner,
        api_key=settings.api_key,
        max_concurrent=settings.max_concurrent,
    )
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write README.md**

`grokgw/README.md`:
```markdown
# grokgw

OpenAI 兼容本地 API 网关,封装 Grok Build CLI(`grok -p`),复用 SuperGrok 订阅认证。

## 前提

- `grok` CLI 已安装(`~/.grok/bin/grok`)且已登录(`~/.grok/auth.json` 存在)
- Python 3.12+

## 安装

```bash
source antibot/.venv/bin/activate   # 或自建 venv
pip install -e ./grokgw
pip install pytest pytest-asyncio httpx   # dev
```

## 运行

```bash
python -m grokgw
# 默认监听 127.0.0.1:8787
```

## 使用

```bash
# 非流式
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}]}'

# 流式
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

OpenAI SDK:
```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="dummy")
resp = client.chat.completions.create(
    model="grok-4.5",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

## 配置(环境变量)

| 变量 | 默认 | 说明 |
|------|------|------|
| `GROKGW_PORT` | 8787 | 监听端口 |
| `GROKGW_HOST` | 127.0.0.1 | 监听地址 |
| `GROKGW_MAX_CONCURRENT` | 3 | 最大并发请求数 |
| `GROKGW_API_KEY` | (无) | 可选,设置后要求客户端 Bearer 认证 |
| `GROKGW_GROK_BIN` | grok | grok 二进制路径 |
| `GROKGW_TIMEOUT` | 120 | 单请求超时(秒) |
| `GROKGW_EXPOSE_REASONING` | false | 是否透传 thought 事件为 reasoning_content |

## 测试

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -m pytest grokgw/tests/ -v
```

## 局限

- **不支持 function calling**(Grok Build headless 的 `--tools` 是内置工具,不接 OpenAI function schema)
- 非流式响应 `usage` 为 null(grok json 输出不含 token 计数)
- 每请求 spawn grok 进程,cold start ~2-5s,适合低并发自用
- SuperGrok token 7 天过期需 `grok login` 刷新

## 设计文档

`docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`
```

- [ ] **Step 3: Add grokgw section to AGENTS.md**

In `AGENTS.md`, append after the "## Browser Ops Runtime (P0)" section:

```markdown

## Grok API Gateway (grokgw)

- Package: `grokgw/` - OpenAI-compatible local API gateway wrapping Grok Build CLI.
- Reuses SuperGrok subscription auth (`~/.grok/auth.json`), no API key needed.
- Entry: from repo root with venv active:
  ```bash
  source antibot/.venv/bin/activate
  python -m grokgw
  ```
- Spec: `docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`
- Plan: `docs/superpowers/plans/2026-07-15-grok-api-gateway.md`
- Each request runs `grok -p` in an isolated empty `/tmp` dir (avoids repo-upload privacy risk).
- No function calling; no multi-account token pool (M3+ evolution).
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest grokgw/tests/ -v`
Expected: all tests PASS

- [ ] **Step 5: Smoke test (manual, requires real grok login)**

```bash
source antibot/.venv/bin/activate
python -m grokgw &
sleep 2
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Reply with exactly PONG"}]}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
# Expected: PONG
kill %1
```

- [ ] **Step 6: Commit**

```bash
git add grokgw/grokgw/__main__.py grokgw/README.md AGENTS.md
git commit -m "feat(grokgw): add entry point, README, AGENTS.md docs"
```

---

### Task 9: Error handling for auth-expired + runner error propagation

**Files:**
- Modify: `grokgw/grokgw/server.py`
- Modify: `grokgw/tests/test_server.py`

- [ ] **Step 1: Add failing tests for error propagation**

Append to `grokgw/tests/test_server.py`:
```python
from grokgw.grok_runner import GrokRunError


class AuthFailRunner:
    """Runner that simulates grok auth failure."""
    async def run(self, args):
        raise GrokRunError("grok exited with code 1: auth error: please run grok login", 1, "auth error")
    async def run_stream(self, args):
        raise GrokRunError("auth error", 1, "auth error")
        yield  # make it a generator


@pytest.fixture
def authfail_app():
    return create_app(runner=AuthFailRunner(), api_key=None, max_concurrent=3)


@pytest.fixture
async def authfail_client(authfail_app):
    transport = ASGITransport(app=authfail_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_expired_returns_401(authfail_client):
    resp = await authfail_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 401
    data = resp.json()
    assert "grok login" in data["error"]["message"].lower()


async def test_generic_runner_error_returns_502():
    class FailRunner:
        async def run(self, args):
            raise GrokRunError("grok exited with code 1: some other error", 1, "error")
        async def run_stream(self, args):
            raise GrokRunError("error", 1, "error")
            yield

    app = create_app(runner=FailRunner(), api_key=None, max_concurrent=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/v1/chat/completions", json={
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "x"}],
        })
        assert resp.status_code == 502


async def test_timeout_returns_504():
    import asyncio as aio

    class TimeoutRunner:
        async def run(self, args):
            raise TimeoutError("grok timed out after 120s")
        async def run_stream(self, args):
            raise TimeoutError("timed out")
            yield

    app = create_app(runner=TimeoutRunner(), api_key=None, max_concurrent=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/v1/chat/completions", json={
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "x"}],
        })
        assert resp.status_code == 504
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: 3 new tests FAIL (no error handling in chat_completions route)

- [ ] **Step 3: Add error handling to chat_completions route**

In `grokgw/grokgw/server.py`, wrap the `chat_completions` route body in try/except. Replace the route function with:

```python
    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        if req.model not in _ALLOWED_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"model '{req.model}' not supported. Available: grok-4.5, grok-build, grok-latest",
            )

        async with sem:
            sandbox_dir = create_sandbox(root=settings.sandbox_root)
            req_id = f"chatcmpl-{__import__('uuid').uuid4().hex[:24]}"
            args = to_cli_args(req, sandbox_dir=sandbox_dir, settings=settings, req_id=req_id)
            try:
                if req.stream:
                    return StreamingResponse(
                        _stream_response(runner, args, req_id, req.model, settings, sandbox_dir),
                        media_type="text/event-stream",
                    )
                else:
                    data = await runner.run(args)
                    return to_openai_response(data, req)
            except GrokRunError as e:
                stderr_lower = e.stderr.lower()
                if "auth" in stderr_lower or "login" in stderr_lower or "credential" in stderr_lower:
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"message": "Grok auth expired. Run: grok login", "type": "authentication_error"}},
                    )
                return JSONResponse(
                    status_code=502,
                    content={"error": {"message": str(e), "type": "upstream_error"}},
                )
            except TimeoutError as e:
                return JSONResponse(
                    status_code=504,
                    content={"error": {"message": str(e), "type": "timeout_error"}},
                )
            finally:
                if not req.stream:
                    cleanup_sandbox(sandbox_dir)
```

Add import at top of server.py:
```python
from grokgw.grok_runner import GrokRunError
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest grokgw/tests/test_server.py -v`
Expected: 13 PASS (10 old + 3 new)

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/server.py grokgw/tests/test_server.py
git commit -m "feat(grokgw): add error handling for auth-expired/timeout/generic runner errors"
```

---

### Task 10: Full integration smoke + final verification

**Files:**
- No new files; verify acceptance criteria V1-V9

- [ ] **Step 1: Run full unit test suite**

Run: `cd /home/zakza/project/research/xpage && source antibot/.venv/bin/activate && python -m pytest grokgw/tests/ -v`
Expected: all PASS (V9)

- [ ] **Step 2: Manual smoke - non-streaming (V1)**

```bash
source antibot/.venv/bin/activate
python -m grokgw &
GROKGW_PID=$!
sleep 3
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Reply with exactly PONG"}]}' \
  | python -c "import sys,json; d=json.load(sys.stdin); print('V1:', d['choices'][0]['message']['content'])"
kill $GROKGW_PID
```
Expected: `V1: PONG`

- [ ] **Step 3: Manual smoke - streaming (V2)**

```bash
source antibot/.venv/bin/activate
python -m grokgw &
GROKGW_PID=$!
sleep 3
curl -sN http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"Say hello in one word"}],"stream":true}' \
  | tail -5
kill $GROKGW_PID
```
Expected: SSE chunks ending with `data: [DONE]`

- [ ] **Step 4: Manual smoke - models (V4) + healthz (V5)**

```bash
source antibot/.venv/bin/activate
python -m grokgw &
GROKGW_PID=$!
sleep 3
echo "=== V4 ===" && curl -s http://127.0.0.1:8787/v1/models | python -m json.tool
echo "=== V5 ===" && curl -s http://127.0.0.1:8787/healthz | python -m json.tool
kill $GROKGW_PID
```
Expected: models list contains grok-4.5 + grok-build; healthz returns status ok

- [ ] **Step 5: Manual smoke - OpenAI SDK compat (V3)**

```bash
source antibot/.venv/bin/activate
python -m grokgw &
GROKGW_PID=$!
sleep 3
python -c "
from openai import OpenAI
c = OpenAI(base_url='http://127.0.0.1:8787/v1', api_key='dummy')
r = c.chat.completions.create(model='grok-4.5', messages=[{'role':'user','content':'Reply OK'}])
print('V3:', r.choices[0].message.content)
"
kill $GROKGW_PID
```
Expected: `V3: OK`

- [ ] **Step 6: Sandbox isolation verification (V8)**

```bash
ls -d /tmp/grokgw-sandbox-* 2>/dev/null | head
# Run a request, then check again - dirs should be cleaned up
source antibot/.venv/bin/activate
python -m grokgw &
GROKGW_PID=$!
sleep 3
curl -s http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"hi"}]}' > /dev/null
sleep 1
kill $GROKGW_PID
echo "remaining sandbox dirs:"; ls -d /tmp/grokgw-sandbox-* 2>/dev/null | wc -l
```
Expected: 0 remaining (all cleaned up after requests)

- [ ] **Step 7: Final commit (if any changes from smoke fixes)**

```bash
git status
# If changes made:
git add -A && git commit -m "test(grokgw): verify acceptance V1-V9 via smoke tests"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- §1.3 Constraints: headless 封装 ✅(Task 5), OpenAI 兼容 ✅(Task 6-7), SSE 流式 ✅(Task 7), function calling 不支持 ✅(无 task,设计标注)
- §1.4 Risks: 仓库上传隔离 ✅(Task 4 sandbox), auth 7天过期 ✅(Task 9), CLI版本防御性解析 ✅(Task 3 unknown type skip), 进程开销限并发 ✅(Task 6 sem)
- §3 Components: config ✅(T1), models ✅(T2), mapping ✅(T3), sandbox ✅(T4), grok_runner ✅(T5), server ✅(T6-7)
- §4 Mapping: to_cli_args ✅(T3), to_sse_chunk ✅(T3), to_openai_response ✅(T3)
- §5 Error handling: 401 auth ✅(T9), 504 timeout ✅(T9), 502 generic ✅(T9), 400 invalid model ✅(T6), 429 concurrency(spec提及) - 注:信号量阻塞而非429(spec说429但实际用sem阻塞更合理,已在T6实现sem;若需429需加非阻塞try_acquire,标为可选增强)
- §6 Testing: unit ✅(T1-T7), runner mock ✅(T5), server mock ✅(T6-7), smoke ✅(T10), V1-V9 ✅(T10)
- §7 Milestones: M0 MVP ✅(T1-T6,8), M1 流式+认证 ✅(T7), M2 健壮性 ✅(T9)

**2. Placeholder scan:** No TBD/TODO. All code blocks contain real implementation. ✅

**3. Type consistency:** `to_cli_args(req, sandbox_dir=, settings=, req_id=)` - signature consistent across T3/T6. `GrokRunError(message, returncode, stderr)` - consistent across T5/T9. `create_app(runner=, api_key=, max_concurrent=)` - consistent across T6/T7/T9. ✅

**One gap identified:** §5 spec mentions 429 for concurrency limit, but Task 6 implements blocking semaphore (waits, not rejects). This is a reasonable simplification - blocking is better UX than 429 for low-concurrency self-use. Documented in self-review, not a plan bug.
