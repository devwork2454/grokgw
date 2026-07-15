from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Result:
    ok: bool
    need_relogin: bool = False
    retryable: bool = False
    message: str = ""


@dataclass
class Proxy:
    id: int
    name: str
    scheme: str
    host: str
    port: int
    auth_ref: Optional[str] = None
    health: str = "unknown"
    last_check_at: Optional[str] = None

    def proxy_url(self) -> str:
        # auth 在 P0 先不拼进 URL（auth_ref 留给后续）；格式 scheme://host:port
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass
class Account:
    id: int
    name: str
    site_key: str
    username: Optional[str]
    secret_ref: Optional[str]
    profile_path: str
    proxy_id: Optional[int]
    status: str = "active"
    last_ok_at: Optional[str] = None
    last_error: Optional[str] = None
    meta_json: str = "{}"
    fail_streak: int = 0
    cooling_until: Optional[str] = None


@dataclass
class SitePolicy:
    site_key: str
    url_allow_prefixes: list[str] = field(default_factory=list)
    min_interval_sec: int = 0
    max_concurrency: int = 1


@dataclass
class Task:
    id: int
    name: str
    account_id: int
    script: str
    schedule: str
    enabled: bool = True
    max_retries: int = 2
    timeout_sec: int = 120
    params_json: str = "{}"
    last_started_at: Optional[str] = None


@dataclass
class TaskRun:
    id: int
    task_id: int
    started_at: str
    finished_at: Optional[str]
    status: str
    error: Optional[str] = None
    log_path: Optional[str] = None


@dataclass
class RunContext:
    tab: Any
    account: Account
    params: dict
    logger: Any
    allowed_prefixes: list[str]
