# grokgw Media Phase 1 (Session Harvest + Serve) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Progress snapshot (2026-07-17)

| 项 | 状态 |
|----|------|
| 实现 + 单测 + README | **DONE**（已 merge main，media 相关 commits / PR #1） |
| 远程 BLR 上 media 验收 | **OUT OF SCOPE**（本周期主线是 proxy 部署，非 CLI media） |

下方 checkbox 可能仍为未勾选历史痕迹；**以本表与 `docs/STATUS.md` 为准**。

**Goal:** 让 CLI 后端 chat 生成图片后，响应文本中的 `images/N.jpg` 被改写为可访问的 HTTP URL，客户端能 `GET` 拿到真实 JPEG（session harvest + static media serve）。

**Architecture:** 不对抗 grok-build 生命周期。图片真实落盘在 `~/.grok/sessions/<urlencoded-cwd>/<sessionId>/images/N.jpg`（不是 sandbox cwd）。Phase 1 只做三件事：`(1)` 按 `sessionId` 安全定位 session 目录；`(2)` `GET /v1/media/sessions/{id}/images/{file}` 提供文件；`(3)` 非流式 `complete` 在拿到 grok JSON 后用 `sessionId` rewrite `text` 中的相对媒体路径。不写 stream rewrite（Phase 2）、不写 OpenAI Images 直连（Phase 3）、不写 video REST（Phase 4）。

**Tech Stack:** Python 3.12、FastAPI、`FileResponse`、pytest、pytest-asyncio、httpx ASGITransport。路径解析对齐 grok-build：`~/.grok/sessions/{urlencode(cwd)}/{sessionId}/images/{n}.jpg`。

**Spec / 决策来源:** 会话内 Hybrid 方案（session harvest 为主）；源码证据见 `/tmp/grok-build` 的 `image_gen` 与 `session/persistence`。

**Notes for agents:**
- 工作区 monorepo 根：`/home/zakza/project/research/xpage`（`origin` = `devwork2454/grokgw`）。包在 `grokgw/`。
- 激活 venv：`source antibot/.venv/bin/activate`；`pip install -e ./grokgw`（若未装）。
- 单测不启真实 `grok`（mock subprocess + 临时 sessions 树）。
- 真机冒烟（可选 Task 6）需 `GROKGW_BACKEND=cli`、`GROKGW_TIMEOUT>=300`、本机 `grok login` + socks5 `127.0.0.1:2080`。
- **YAGNI：** 不实现 video 端点、stream rewrite、Imagine 直连、TTL 清理、`GROKGW_MEDIA=auto` 意图检测。Phase 1 的 media 服务始终可读（若文件存在）；rewrite 仅在 `sessionId` 存在且 text 含相对路径时发生。
- Commit 消息用英文 conventional commits；代码注释用中文（项目惯例）。
- 每个 Task 结束后跑该 Task 相关 pytest，全部绿再 commit。

---

## File map (create / modify)

| Path | Responsibility |
|------|----------------|
| `grokgw/grokgw/media.py` | **Create.** `find_session_dir`、`resolve_media_file`、`rewrite_media_paths`、路径安全校验 |
| `grokgw/tests/test_media.py` | **Create.** media 纯函数单测 |
| `grokgw/grokgw/config.py` | **Modify.** `sessions_root`、`public_base`、`media_enabled` 及 env |
| `grokgw/tests/test_config.py` | **Modify.** 新 settings 字段断言 |
| `grokgw/grokgw/grok_runner.py` | **Modify.** `complete()` 在 `to_openai_response` 前 rewrite text |
| `grokgw/tests/test_grok_runner.py` | **Modify.** complete rewrite 集成（mock run） |
| `grokgw/grokgw/server.py` | **Modify.** `GET /v1/media/...`；`create_app` 可注入 `settings`；healthz 暴露 media 标记；auth 白名单不含 media |
| `grokgw/tests/test_server.py` | **Modify.** media 路由 200/404/traversal；auth 覆盖 |
| `grokgw/README.md` | **Modify.** 端点 + 环境变量 + 简短用法 |
| `docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md` | **Optional light touch.** 不阻塞 Phase 1；若改只加一小段 media 指针 |

**Out of scope (do not touch):**
- `mapping.py` stream 路径 rewrite（Phase 2）
- `proxy_runner.py` / Imagine REST（Phase 3）
- video-specific routes（Phase 4；但 rewrite regex 可预留 `videos/` 以降低 Phase 4 改动——**仅 rewrite + resolve 允许 videos，serve 路由 Phase 1 只挂 images 亦可；本计划 serve 同时支持 images/videos 文件类型，因实现成本为零**）

---

## Ground truth（实现前必读，勿再发明）

1. **落盘路径**（已验证）  
   `~/.grok/sessions/%2Ftmp/<sessionId>/images/1.jpg`  
   布局：`{sessions_root}/{urlencoded_cwd}/{sessionId}/images|videos/{n}.{ext}`  
   `sessionId` 形如 `019f69f6-cf7f-7711-b38e-45b3cecc1762`（UUID 变体）。

2. **find by id**（对齐 grok-build `locate_session_dir`）  
   遍历 `sessions_root` **一层**子目录，找 `child / session_id` 为目录者。

3. **CLI JSON 契约**（已有测试数据）  
   `{"text":"... images/1.jpg ...","stopReason":"EndTurn","sessionId":"s1","requestId":"q1"}`  
   headless **不**发 tool 事件；rewrite 只能基于最终 `text` + `sessionId`。

4. **sandbox 清理**  
   `cleanup_sandbox()` 只删 `/tmp/grokgw-sandbox-*`，**不会**删 `~/.grok/sessions` 图片。rewrite 后无需 copy。

5. **超时**  
   上游 image ~300s；默认 `GROKGW_TIMEOUT=120` 不够。Phase 1：当 `media_enabled` 为真时，若 env 未显式设 `GROKGW_TIMEOUT`，默认 timeout 提到 **300**。显式 env 始终优先。

---

### Task 1: `media.py` 纯函数 + 单测（TDD）

**Files:**
- Create: `grokgw/grokgw/media.py`
- Create: `grokgw/tests/test_media.py`

- [ ] **Step 1: Write the failing tests**

`grokgw/tests/test_media.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from grokgw.media import (
    find_session_dir,
    resolve_media_file,
    rewrite_media_paths,
    MediaPathError,
)


def _mk_session_tree(root: Path, cwd_key: str, session_id: str, rel: str, data: bytes) -> Path:
    """Create sessions_root/cwd_key/session_id/<rel> with bytes."""
    target = root / cwd_key / session_id / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_find_session_dir_finds_across_cwd_keys(tmp_path: Path):
    sid = "019f69f6-cf7f-7711-b38e-45b3cecc1762"
    _mk_session_tree(tmp_path, "%2Ftmp", sid, "images/1.jpg", b"\xff\xd8fake")
    found = find_session_dir(tmp_path, sid)
    assert found == tmp_path / "%2Ftmp" / sid


def test_find_session_dir_missing_returns_none(tmp_path: Path):
    assert find_session_dir(tmp_path, "no-such-session") is None


def test_find_session_dir_rejects_path_traversal(tmp_path: Path):
    assert find_session_dir(tmp_path, "../etc") is None
    assert find_session_dir(tmp_path, "a/b") is None
    assert find_session_dir(tmp_path, "") is None


def test_resolve_media_file_ok(tmp_path: Path):
    sid = "019f69f6-cf7f-7711-b38e-45b3cecc1762"
    _mk_session_tree(tmp_path, "%2Ftmp", sid, "images/1.jpg", b"JPEGDATA")
    path = resolve_media_file(tmp_path, sid, "images", "1.jpg")
    assert path.read_bytes() == b"JPEGDATA"


def test_resolve_media_file_videos_ok(tmp_path: Path):
    sid = "019f69f6-cf7f-7711-b38e-45b3cecc1762"
    _mk_session_tree(tmp_path, "%2Ftmp", sid, "videos/1.mp4", b"mp4")
    path = resolve_media_file(tmp_path, sid, "videos", "1.mp4")
    assert path.read_bytes() == b"mp4"


def test_resolve_media_file_unknown_kind(tmp_path: Path):
    with pytest.raises(MediaPathError):
        resolve_media_file(tmp_path, "sid", "etc", "1.jpg")


def test_resolve_media_file_bad_filename(tmp_path: Path):
    with pytest.raises(MediaPathError):
        resolve_media_file(tmp_path, "sid", "images", "../secret")
    with pytest.raises(MediaPathError):
        resolve_media_file(tmp_path, "sid", "images", "1.exe")


def test_resolve_media_file_missing_raises(tmp_path: Path):
    with pytest.raises(MediaPathError):
        resolve_media_file(tmp_path, "nope", "images", "1.jpg")


def test_rewrite_media_paths_basic():
    text = "Saved to images/1.jpg for you."
    out = rewrite_media_paths(
        text, base="http://127.0.0.1:8787", session_id="abc-123"
    )
    assert out == "Saved to http://127.0.0.1:8787/v1/media/sessions/abc-123/images/1.jpg for you."


def test_rewrite_media_paths_multiple_and_videos():
    text = "see images/1.jpg and videos/2.mp4 and images/3.png"
    out = rewrite_media_paths(text, base="http://x", session_id="s1")
    assert "http://x/v1/media/sessions/s1/images/1.jpg" in out
    assert "http://x/v1/media/sessions/s1/videos/2.mp4" in out
    assert "http://x/v1/media/sessions/s1/images/3.png" in out


def test_rewrite_media_paths_no_false_positive():
    text = "path/images/1.jpg should not match; also myimages/1.jpg"
    out = rewrite_media_paths(text, base="http://x", session_id="s1")
    # only bare `images/N.ext` or `videos/N.ext` (not preceded by word or /)
    assert "path/images/1.jpg" in out  # left alone
    assert "myimages/1.jpg" in out  # left alone


def test_rewrite_media_paths_empty_session_noop():
    text = "images/1.jpg"
    assert rewrite_media_paths(text, base="http://x", session_id="") == text
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
pip install -e ./grokgw -q
python -m pytest grokgw/tests/test_media.py -v
```

Expected: `ModuleNotFoundError: No module named 'grokgw.media'` 或 import 失败。

- [ ] **Step 3: Implement `grokgw/grokgw/media.py`**

```python
from __future__ import annotations

import re
from pathlib import Path

# session id: no path separators, reasonable length, alnum + _.-
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEDIA_KINDS = frozenset({"images", "videos"})
_FILE_RE = re.compile(r"^\d+\.(?:jpg|jpeg|png|webp|mp4)$", re.IGNORECASE)
# 相对路径：不以 \w 或 / 开头（避免 path/images 与 myimages）
_MEDIA_PATH_RE = re.compile(
    r"(?<![\w/])(?P<kind>images|videos)/(?P<name>\d+\.(?:jpg|jpeg|png|webp|mp4))",
    re.IGNORECASE,
)


class MediaPathError(ValueError):
    """非法媒体路径或文件不存在。"""


def _valid_session_id(session_id: str) -> bool:
    if not session_id or ".." in session_id or "/" in session_id or "\\" in session_id:
        return False
    return bool(_SESSION_ID_RE.match(session_id))


def find_session_dir(sessions_root: Path | str, session_id: str) -> Path | None:
    """在 sessions_root 下一层 cwd 目录中查找 session_id 目录。"""
    if not _valid_session_id(session_id):
        return None
    root = Path(sessions_root)
    if not root.is_dir():
        return None
    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            candidate = entry / session_id
            if candidate.is_dir():
                return candidate.resolve()
    except OSError:
        return None
    return None


def resolve_media_file(
    sessions_root: Path | str,
    session_id: str,
    kind: str,
    filename: str,
) -> Path:
    """返回真实媒体文件路径；非法或缺失则抛 MediaPathError。"""
    if kind not in _MEDIA_KINDS:
        raise MediaPathError(f"invalid media kind: {kind}")
    if not _FILE_RE.match(filename or ""):
        raise MediaPathError(f"invalid media filename: {filename}")
    session_dir = find_session_dir(sessions_root, session_id)
    if session_dir is None:
        raise MediaPathError(f"session not found: {session_id}")
    # 强制在 session_dir/kind/filename 下，resolve 后校验前缀
    path = (session_dir / kind / filename).resolve()
    try:
        path.relative_to(session_dir.resolve())
    except ValueError as e:
        raise MediaPathError("path escapes session dir") from e
    if not path.is_file():
        raise MediaPathError(f"media file not found: {kind}/{filename}")
    return path


def rewrite_media_paths(text: str, *, base: str, session_id: str) -> str:
    """把 text 中的 images|videos/N.ext 改写为可访问 URL。"""
    if not text or not session_id or not base:
        return text
    if not _valid_session_id(session_id):
        return text
    base = base.rstrip("/")

    def repl(m: re.Match[str]) -> str:
        kind = m.group("kind").lower()
        name = m.group("name")
        return f"{base}/v1/media/sessions/{session_id}/{kind}/{name}"

    return _MEDIA_PATH_RE.sub(repl, text)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest grokgw/tests/test_media.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
cd /home/zakza/project/research/xpage
git add grokgw/grokgw/media.py grokgw/tests/test_media.py
git commit -m "$(cat <<'EOF'
feat(grokgw): add media path resolve and rewrite helpers

Session harvest helpers locate grok session dirs under
~/.grok/sessions and rewrite relative images/videos paths
to gateway URLs without copying files.
EOF
)"
```

---

### Task 2: Settings — `sessions_root` / `public_base` / `media_enabled` + media 默认超时

**Files:**
- Modify: `grokgw/grokgw/config.py`
- Modify: `grokgw/tests/test_config.py`

- [ ] **Step 1: Write/extend failing tests**

在 `grokgw/tests/test_config.py` 追加：

```python
import os
from grokgw.config import Settings


def test_media_defaults():
    s = Settings()
    assert s.media_enabled is True
    assert s.sessions_root == os.path.expanduser("~/.grok/sessions")
    # public_base 默认由 host:port 推导
    assert s.public_base == "http://127.0.0.1:8787"


def test_media_env_override(monkeypatch):
    monkeypatch.setenv("GROKGW_MEDIA", "0")
    monkeypatch.setenv("GROKGW_SESSIONS_ROOT", "/tmp/fake-sessions")
    monkeypatch.setenv("GROKGW_PUBLIC_BASE", "http://example.local:9000")
    monkeypatch.setenv("GROKGW_HOST", "0.0.0.0")
    monkeypatch.setenv("GROKGW_PORT", "9000")
    s = Settings.from_env()
    assert s.media_enabled is False
    assert s.sessions_root == "/tmp/fake-sessions"
    assert s.public_base == "http://example.local:9000"


def test_media_enabled_timeout_default_when_unset(monkeypatch):
    """media on + no GROKGW_TIMEOUT → timeout 至少 300。"""
    monkeypatch.delenv("GROKGW_TIMEOUT", raising=False)
    monkeypatch.setenv("GROKGW_MEDIA", "1")
    s = Settings.from_env()
    assert s.media_enabled is True
    assert s.timeout == 300


def test_explicit_timeout_wins(monkeypatch):
    monkeypatch.setenv("GROKGW_MEDIA", "1")
    monkeypatch.setenv("GROKGW_TIMEOUT", "90")
    s = Settings.from_env()
    assert s.timeout == 90
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python -m pytest grokgw/tests/test_config.py -v
```

- [ ] **Step 3: Implement config changes**

在 `Settings` dataclass 增加字段（保留现有字段）：

```python
_DEFAULT_SESSIONS = os.path.expanduser("~/.grok/sessions")
_MEDIA_TIMEOUT_DEFAULT = 300

@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    media_enabled: bool = True
    sessions_root: str = _DEFAULT_SESSIONS
    public_base: str = "http://127.0.0.1:8787"
```

`from_env` 逻辑要点：

```python
host = os.environ.get("GROKGW_HOST", "127.0.0.1")
port = int(os.environ.get("GROKGW_PORT", "8787"))
media_enabled = _get_bool("GROKGW_MEDIA", True)
# public_base: env 优先，否则 http://{host}:{port}；host 为 0.0.0.0 时用 127.0.0.1
if "GROKGW_PUBLIC_BASE" in os.environ and os.environ["GROKGW_PUBLIC_BASE"].strip():
    public_base = os.environ["GROKGW_PUBLIC_BASE"].rstrip("/")
else:
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    public_base = f"http://{display_host}:{port}"

if "GROKGW_TIMEOUT" in os.environ:
    timeout = int(os.environ["GROKGW_TIMEOUT"])
elif media_enabled:
    timeout = _MEDIA_TIMEOUT_DEFAULT
else:
    timeout = 120

sessions_root = os.environ.get("GROKGW_SESSIONS_ROOT") or _DEFAULT_SESSIONS
sessions_root = os.path.expanduser(sessions_root)
```

注意：`test_defaults` 里 `Settings()` 直接构造仍应 `timeout==120`（dataclass 默认不变）；只有 `from_env` 在 media on 且未设 TIMEOUT 时变 300。若现有 `test_defaults` 测的是 `Settings()` 不是 `from_env()`，无需改 timeout 断言。

- [ ] **Step 4: Run — expect PASS**

```bash
python -m pytest grokgw/tests/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/config.py grokgw/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(grokgw): add media settings and longer default timeout

Expose GROKGW_MEDIA, GROKGW_SESSIONS_ROOT, GROKGW_PUBLIC_BASE
and default timeout to 300s when media is enabled.
EOF
)"
```

---

### Task 3: `GrokRunner.complete` 改写 text

**Files:**
- Modify: `grokgw/grokgw/grok_runner.py`
- Modify: `grokgw/tests/test_grok_runner.py`

- [ ] **Step 1: Write failing test**

在 `test_grok_runner.py` 追加：

```python
async def test_complete_rewrites_media_paths(monkeypatch):
    """Given grok json with sessionId + images/1.jpg, When complete, Then content URL-rewritten."""
    from grokgw.models import ChatCompletionRequest, Message

    json_out = (
        b'{"text":"Here: images/1.jpg","stopReason":"EndTurn",'
        b'"sessionId":"sess-abc","requestId":"q1"}\n'
    )
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    # 避免真 sandbox IO：固定 cwd
    r = GrokRunner(
        Settings(
            media_enabled=True,
            public_base="http://127.0.0.1:8787",
            grok_cwd="/tmp",  # 不 cleanup sandbox
            timeout=5,
        )
    )
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="draw")],
    )
    resp = await r.complete(req)
    content = resp["choices"][0]["message"]["content"]
    assert content == "Here: http://127.0.0.1:8787/v1/media/sessions/sess-abc/images/1.jpg"


async def test_complete_no_rewrite_when_media_disabled(monkeypatch):
    from grokgw.models import ChatCompletionRequest, Message

    json_out = (
        b'{"text":"Here: images/1.jpg","stopReason":"EndTurn",'
        b'"sessionId":"sess-abc","requestId":"q1"}\n'
    )
    proc = MockProc(stdout_lines=[json_out], returncode=0)

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr("grokgw.grok_runner.asyncio.create_subprocess_exec", fake_create)
    r = GrokRunner(
        Settings(media_enabled=False, public_base="http://127.0.0.1:8787", grok_cwd="/tmp")
    )
    req = ChatCompletionRequest(
        model="grok-4.5",
        messages=[Message(role="user", content="draw")],
    )
    resp = await r.complete(req)
    assert resp["choices"][0]["message"]["content"] == "Here: images/1.jpg"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python -m pytest grokgw/tests/test_grok_runner.py::test_complete_rewrites_media_paths -v
```

- [ ] **Step 3: Implement in `complete`**

`grokgw/grok_runner.py`：

```python
from grokgw.media import rewrite_media_paths

# inside complete(), after data = await self.run(args):
if self._settings.media_enabled:
    sid = data.get("sessionId") or ""
    text = data.get("text") or ""
    if sid and text:
        data = {
            **data,
            "text": rewrite_media_paths(
                text,
                base=self._settings.public_base,
                session_id=sid,
            ),
        }
return to_openai_response(data, req)
```

注意：`data` 可能需要浅拷贝再改 `text`，避免污染（上面 dict 展开已是新 dict）。

**不要**在 `stream()` 做 rewrite（Phase 2）。

- [ ] **Step 4: Run full runner tests**

```bash
python -m pytest grokgw/tests/test_grok_runner.py -v
```

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/grok_runner.py grokgw/tests/test_grok_runner.py
git commit -m "$(cat <<'EOF'
feat(grokgw): rewrite session media paths in CLI complete responses

When media is enabled, map images/N.jpg in grok JSON text to
gateway media URLs using sessionId from the CLI payload.
EOF
)"
```

---

### Task 4: FastAPI media 路由 + create_app settings 注入

**Files:**
- Modify: `grokgw/grokgw/server.py`
- Modify: `grokgw/grokgw/__main__.py`（若签名变，传入 settings）
- Modify: `grokgw/tests/test_server.py`

- [ ] **Step 1: Write failing tests**

在 `test_server.py` 追加（用 tmp_path 造 sessions 树 + monkeypatch settings 注入）：

```python
from pathlib import Path

from grokgw.config import Settings
from grokgw.server import create_app


def _app_with_sessions(tmp_path: Path, api_key: str | None = None):
    sid = "019f69f6-cf7f-7711-b38e-45b3cecc1762"
    img = tmp_path / "%2Ftmp" / sid / "images" / "1.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\xff\xd8\xffJPEGTEST")
    settings = Settings(
        media_enabled=True,
        sessions_root=str(tmp_path),
        public_base="http://test",
        api_key=api_key,
    )
    return create_app(
        runner=FakeRunner(),
        api_key=api_key,
        max_concurrent=3,
        settings=settings,
    ), sid


async def test_media_image_ok(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/1.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content.startswith(b"\xff\xd8")


async def test_media_image_missing_404(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/99.jpg")
    assert resp.status_code == 404


async def test_media_path_traversal_rejected(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/v1/media/sessions/../etc/images/1.jpg")
    assert resp.status_code in (400, 404, 422)


async def test_media_requires_api_key_when_set(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path, api_key="secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/1.jpg")
        assert resp.status_code == 401
        resp2 = await c.get(
            f"/v1/media/sessions/{sid}/images/1.jpg",
            headers={"Authorization": "Bearer secret-key"},
        )
        assert resp2.status_code == 200


async def test_healthz_includes_media_flag(tmp_path: Path):
    app, _ = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json().get("media_enabled") is True
```

- [ ] **Step 2: Run — expect FAIL**（缺路由 / 缺 settings 参数）

```bash
python -m pytest grokgw/tests/test_server.py -v -k media
```

- [ ] **Step 3: Implement server**

`create_app` 签名改为：

```python
def create_app(
    *,
    runner: RunnerProtocol,
    api_key: str | None,
    max_concurrent: int,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
```

路由：

```python
from fastapi.responses import FileResponse
from grokgw.media import MediaPathError, resolve_media_file

@app.get("/v1/media/sessions/{session_id}/{kind}/{filename}")
async def get_media(session_id: str, kind: str, filename: str):
    if not settings.media_enabled:
        raise HTTPException(status_code=404, detail="media disabled")
    try:
        path = resolve_media_file(
            settings.sessions_root, session_id, kind, filename
        )
    except MediaPathError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
    }
    mt = media_types.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mt)
```

`healthz` 增加：

```python
"media_enabled": settings.media_enabled,
"sessions_root": settings.sessions_root if settings.media_enabled else None,
"public_base": settings.public_base if settings.media_enabled else None,
```

auth 中间件：media 路径**不**加入白名单（与 chat 同鉴权）。

`__main__.py`：

```python
app = create_app(
    runner=runner,
    api_key=settings.api_key,
    max_concurrent=settings.max_concurrent,
    settings=settings,
)
```

- [ ] **Step 4: Run all server tests**

```bash
python -m pytest grokgw/tests/test_server.py -v
```

- [ ] **Step 5: Commit**

```bash
git add grokgw/grokgw/server.py grokgw/grokgw/__main__.py grokgw/tests/test_server.py
git commit -m "$(cat <<'EOF'
feat(grokgw): serve session media files over HTTP

Add GET /v1/media/sessions/{id}/{kind}/{file} backed by
~/.grok/sessions harvest, with path validation and auth.
EOF
)"
```

---

### Task 5: README + 全量回归

**Files:**
- Modify: `grokgw/README.md`

- [ ] **Step 1: 更新 README 文档表**

在 API 表增加：

| `/v1/media/sessions/{session_id}/images|videos/{file}` | GET | 提供 CLI 会话落盘的图片/视频 |

环境变量表增加：

| `GROKGW_MEDIA` | `true` | 是否启用 media rewrite + 服务 |
| `GROKGW_SESSIONS_ROOT` | `~/.grok/sessions` | grok session 根目录 |
| `GROKGW_PUBLIC_BASE` | `http://{host}:{port}` | rewrite URL 的 base |
| `GROKGW_TIMEOUT` | media 开时默认 `300` | 秒；显式设置优先 |

简短说明（中文）：

```markdown
### 图片（CLI 后端）

`GROKGW_BACKEND=cli` 时，模型生成的 `images/N.jpg` 会改写为：

`http://127.0.0.1:8787/v1/media/sessions/<sessionId>/images/N.jpg`

文件来自本机 `~/.grok/sessions`，与 sandbox 清理无关。生成较慢，请设 `GROKGW_TIMEOUT=300` 或依赖 media 默认超时。
```

- [ ] **Step 2: 全量单测**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
python -m pytest grokgw/tests/ -v
```

Expected: 全部 PASS（原有 ~55 + 新测约 20+）。

- [ ] **Step 3: Commit**

```bash
git add grokgw/README.md
git commit -m "$(cat <<'EOF'
docs(grokgw): document media endpoints and env vars
EOF
)"
```

---

### Task 6（可选冒烟，不强制 commit）: 真机 CLI 画图

**仅在本机有 grok 登录 + 代理时执行。失败不阻塞 Phase 1 合并。**

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
# 若 8787 已被占用，先停旧进程
GROKGW_BACKEND=cli GROKGW_MEDIA=1 GROKGW_TIMEOUT=360 \
  python -m grokgw &
sleep 1
curl -sS http://127.0.0.1:8787/healthz | python -m json.tool
# 非流式生图（可能 1–5 分钟）
RESP=$(curl -sS http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4.5","messages":[{"role":"user","content":"画一只简笔画猫，只要一张图"}]}')
echo "$RESP" | python -m json.tool | head -80
# 从 content 抽出 URL 并 GET
URL=$(echo "$RESP" | python -c "import sys,json,re; t=json.load(sys.stdin)['choices'][0]['message']['content']; m=re.search(r'http://\\S+/v1/media/\\S+', t); print(m.group(0) if m else '')")
echo "URL=$URL"
test -n "$URL"
curl -sS -o /tmp/grokgw-media-smoke.jpg -w "%{http_code} %{content_type}\n" "$URL"
file /tmp/grokgw-media-smoke.jpg
```

验收：
- chat 200
- content 含 `/v1/media/sessions/.../images/...`
- GET 200 + `image/jpeg` + `file` 识别为 JPEG

---

## Self-review checklist

| Spec 项 | Task |
|---------|------|
| `find_session_dir` + 安全路径 | Task 1 |
| `GET /v1/media/sessions/{id}/images/{n}.jpg` | Task 4 |
| `complete` 读 `sessionId` rewrite text | Task 3 |
| media 相关 timeout 上调 | Task 2 |
| 测试：rewrite + serve | Task 1/3/4；冒烟 Task 6 |
| 不实现 stream rewrite | 明确 out of scope |
| 不 watch sandbox cwd | 不写 |
| 不 b64 塞 chat | 不写 |
| 不 fork grok-build | 不写 |

**Placeholder scan:** 无 TBD；测试代码与实现代码均给出。

**类型一致：** `Settings.media_enabled: bool`、`sessions_root: str`、`public_base: str`；`MediaPathError`；`resolve_media_file(...) -> Path`；`rewrite_media_paths(text, *, base, session_id) -> str`。

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-grokgw-media-phase1.md`.

**推荐执行方式：Subagent-Driven Development**
- 每个 Task 一个 fresh subagent
- Task 间 orchestrator 审查 diff + 跑测
- Task 1→2→3→4 顺序（依赖链）；Task 5 在 1–4 后；Task 6 可选

**备选：Inline Execution**（本会话按任务批处理 + checkpoint）
