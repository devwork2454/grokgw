import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from grokgw.auth import AuthError, ensure_access_token, load_auth


def _write_auth(path: Path, *, expires_delta: timedelta, with_refresh: bool = True) -> None:
    expires = datetime.now(timezone.utc) + expires_delta
    entry = {
        "key": "access-token-abc",
        "auth_mode": "oidc",
        "refresh_token": "refresh-token-xyz" if with_refresh else "",
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "oidc_issuer": "https://auth.x.ai",
        "oidc_client_id": "client-123",
    }
    path.write_text(json.dumps({"https://auth.x.ai::client-123": entry}))


def test_load_auth_reads_token(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, expires_delta=timedelta(hours=1))
    auth = load_auth(auth_file)
    assert auth.access_token == "access-token-abc"
    assert auth.refresh_token == "refresh-token-xyz"
    assert auth.client_id == "client-123"
    assert auth.issuer == "https://auth.x.ai"
    assert auth.is_expired is False


def test_load_auth_detects_expiry(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, expires_delta=timedelta(hours=-1))
    auth = load_auth(auth_file)
    assert auth.is_expired is True


def test_load_auth_missing_file(tmp_path: Path):
    with pytest.raises(AuthError, match="not found"):
        load_auth(tmp_path / "nope.json")


def test_ensure_access_token_returns_fresh(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, expires_delta=timedelta(hours=1))
    token = ensure_access_token(auth_file)
    assert token == "access-token-abc"


def test_ensure_access_token_expired_without_refresh_raises(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, expires_delta=timedelta(hours=-1), with_refresh=False)
    with pytest.raises(AuthError, match="expired"):
        ensure_access_token(auth_file)
