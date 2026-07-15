from __future__ import annotations

import fcntl
import time
from pathlib import Path
from typing import Optional

from runtime.browser import BrowserRuntime, BrowserSession
from runtime.models import Account, Proxy


class ProfileLock:
    def __init__(self, profile_dir: Path, timeout: float = 30.0):
        self.profile_dir = Path(profile_dir)
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.profile_dir / ".runtime.lock"
        self._fh = open(lock_path, "a+")
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    self._fh.close()
                    raise TimeoutError(f"profile busy: {self.profile_dir}")
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self._fh:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


class SessionManager:
    def __init__(self, runtime: Optional[BrowserRuntime] = None):
        self.runtime = runtime or BrowserRuntime()

    def open(
        self, account: Account, proxy: Proxy, *, stealth: bool = True
    ) -> tuple[BrowserSession, ProfileLock]:
        lock = ProfileLock(Path(account.profile_path))
        lock.__enter__()
        try:
            sess = self.runtime.start(
                Path(account.profile_path),
                proxy.proxy_url(),
                stealth=stealth,
                ephemeral=False,
            )
            return sess, lock
        except Exception:
            lock.__exit__(None, None, None)
            raise

    def close(self, sess: BrowserSession, lock: ProfileLock) -> None:
        try:
            self.runtime.stop(sess)
        finally:
            lock.__exit__(None, None, None)
