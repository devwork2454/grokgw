from __future__ import annotations
import shutil
import tempfile


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
