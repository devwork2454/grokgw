from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class GrokAuth:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    client_id: str | None
    issuer: str | None
    entry_key: str

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # refresh 60s early
        return datetime.now(timezone.utc).timestamp() >= self.expires_at.timestamp() - 60


def _parse_expires(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_auth(path: Path | str) -> GrokAuth:
    p = Path(path).expanduser()
    if not p.is_file():
        raise AuthError(f"auth file not found: {p}. Run: grok login")
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise AuthError(f"invalid auth file {p}: {e}") from e
    if not isinstance(data, dict):
        raise AuthError(f"invalid auth file shape: {p}")

    best: GrokAuth | None = None
    for entry_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        token = entry.get("key") or entry.get("access_token")
        if not token or not isinstance(token, str):
            continue
        auth = GrokAuth(
            access_token=token,
            refresh_token=entry.get("refresh_token") or None,
            expires_at=_parse_expires(entry.get("expires_at")),
            client_id=entry.get("oidc_client_id"),
            issuer=entry.get("oidc_issuer"),
            entry_key=str(entry_key),
        )
        if best is None or (not auth.is_expired and best.is_expired):
            best = auth
    if best is None:
        raise AuthError(f"no access token in {p}. Run: grok login")
    return best


def _refresh_token(auth: GrokAuth) -> dict:
    if not auth.refresh_token or not auth.issuer or not auth.client_id:
        raise AuthError("token expired and cannot refresh. Run: grok login")
    token_url = auth.issuer.rstrip("/") + "/oauth2/token"
    body = urlencode({
        "grant_type": "refresh_token",
        "refresh_token": auth.refresh_token,
        "client_id": auth.client_id,
    }).encode()
    req = Request(
        token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise AuthError(f"token refresh failed: HTTP {e.code} {detail}") from e
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise AuthError(f"token refresh failed: {e}") from e


def _persist_refreshed(path: Path, auth: GrokAuth, token_payload: dict) -> str:
    data = json.loads(path.read_text())
    entry = data.get(auth.entry_key)
    if not isinstance(entry, dict):
        raise AuthError("auth entry disappeared during refresh")
    access = token_payload.get("access_token")
    if not access:
        raise AuthError("refresh response missing access_token")
    entry["key"] = access
    if token_payload.get("refresh_token"):
        entry["refresh_token"] = token_payload["refresh_token"]
    expires_in = token_payload.get("expires_in")
    if isinstance(expires_in, (int, float)):
        exp = datetime.now(timezone.utc).timestamp() + float(expires_in)
        entry["expires_at"] = datetime.fromtimestamp(exp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
    path.write_text(json.dumps(data, indent=2))
    return access


def ensure_access_token(path: Path | str) -> str:
    p = Path(path).expanduser()
    auth = load_auth(p)
    if not auth.is_expired:
        return auth.access_token
    if not auth.refresh_token:
        raise AuthError("Grok auth expired. Run: grok login")
    payload = _refresh_token(auth)
    return _persist_refreshed(p, auth, payload)
