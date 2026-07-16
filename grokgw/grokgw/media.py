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
