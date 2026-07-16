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
