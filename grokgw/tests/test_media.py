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
