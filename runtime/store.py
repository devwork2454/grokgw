from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from runtime import paths
from runtime.models import Account, Proxy, SitePolicy, Task, TaskRun


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path is not None else paths.DB_PATH
        # For temp/test DBs use sibling "profiles"; default production uses paths.PROFILES
        if self.db_path.resolve() == paths.DB_PATH.resolve():
            self._profiles_base = paths.PROFILES
        else:
            self._profiles_base = self.db_path.parent / "profiles"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        paths.ensure_data_dirs()
        self._profiles_base.mkdir(parents=True, exist_ok=True)
        schema = paths.SCHEMA_SQL.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
            conn.commit()

    # ---- proxies ----

    def add_proxy(
        self,
        name: str,
        scheme: str,
        host: str,
        port: int,
        auth_ref: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO proxies (name, scheme, host, port, auth_ref)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, scheme, host, port, auth_ref),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_proxies(self) -> list[Proxy]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM proxies ORDER BY id").fetchall()
        return [self._row_to_proxy(r) for r in rows]

    def get_proxy(self, id: int) -> Optional[Proxy]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proxies WHERE id = ?", (id,)).fetchone()
        return self._row_to_proxy(row) if row else None

    def get_proxy_by_name(self, name: str) -> Optional[Proxy]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proxies WHERE name = ?", (name,)
            ).fetchone()
        return self._row_to_proxy(row) if row else None

    def set_proxy_health(self, id: int, health: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE proxies
                SET health = ?, last_check_at = ?
                WHERE id = ?
                """,
                (health, _now(), id),
            )
            conn.commit()

    @staticmethod
    def _row_to_proxy(row: sqlite3.Row) -> Proxy:
        return Proxy(
            id=row["id"],
            name=row["name"],
            scheme=row["scheme"],
            host=row["host"],
            port=row["port"],
            auth_ref=row["auth_ref"],
            health=row["health"],
            last_check_at=row["last_check_at"],
        )

    # ---- accounts ----

    def add_account(
        self,
        name: str,
        site_key: str,
        username: Optional[str] = None,
        proxy_id: Optional[int] = None,
        secret_ref: Optional[str] = None,
    ) -> int:
        # Insert with a temporary profile_path, then set to profiles/<id>
        placeholder = str(self._profiles_base / "_pending")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO accounts
                  (name, site_key, username, secret_ref, profile_path, proxy_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, site_key, username, secret_ref, placeholder, proxy_id),
            )
            aid = int(cur.lastrowid)
            profile_path = self._profiles_base / str(aid)
            profile_path.mkdir(parents=True, exist_ok=True)
            conn.execute(
                "UPDATE accounts SET profile_path = ? WHERE id = ?",
                (str(profile_path), aid),
            )
            conn.commit()
            return aid

    def get_account(self, id: int) -> Optional[Account]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (id,)).fetchone()
        return self._row_to_account(row) if row else None

    def get_account_by_name(self, name: str) -> Optional[Account]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE name = ?", (name,)
            ).fetchone()
        return self._row_to_account(row) if row else None

    def list_accounts(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [self._row_to_account(r) for r in rows]

    def update_account_status(
        self, id: int, status: str, last_error: Optional[str] = None
    ) -> None:
        with self._connect() as conn:
            if last_error is not None:
                conn.execute(
                    """
                    UPDATE accounts
                    SET status = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (status, last_error, id),
                )
            else:
                conn.execute(
                    "UPDATE accounts SET status = ? WHERE id = ?",
                    (status, id),
                )
            conn.commit()

    def bump_fail_streak(self, id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE accounts SET fail_streak = fail_streak + 1 WHERE id = ?",
                (id,),
            )
            conn.commit()

    def clear_fail_streak(self, id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET fail_streak = 0, last_ok_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (_now(), id),
            )
            conn.commit()

    def set_cooling(self, id: int, until_iso: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE accounts SET cooling_until = ? WHERE id = ?",
                (until_iso, id),
            )
            conn.commit()

    @staticmethod
    def _row_to_account(row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            site_key=row["site_key"],
            username=row["username"],
            secret_ref=row["secret_ref"],
            profile_path=row["profile_path"],
            proxy_id=row["proxy_id"],
            status=row["status"],
            last_ok_at=row["last_ok_at"],
            last_error=row["last_error"],
            meta_json=row["meta_json"],
            fail_streak=row["fail_streak"],
            cooling_until=row["cooling_until"],
        )

    # ---- site policies ----

    def set_policy(
        self,
        site_key: str,
        prefixes: list[str],
        min_interval_sec: int = 0,
        max_concurrency: int = 1,
    ) -> None:
        prefix_json = json.dumps(prefixes, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO site_policies
                  (site_key, url_allow_prefix, min_interval_sec, max_concurrency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(site_key) DO UPDATE SET
                  url_allow_prefix = excluded.url_allow_prefix,
                  min_interval_sec = excluded.min_interval_sec,
                  max_concurrency = excluded.max_concurrency
                """,
                (site_key, prefix_json, min_interval_sec, max_concurrency),
            )
            conn.commit()

    def get_policy(self, site_key: str) -> Optional[SitePolicy]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM site_policies WHERE site_key = ?", (site_key,)
            ).fetchone()
        if not row:
            return None
        prefixes = json.loads(row["url_allow_prefix"] or "[]")
        return SitePolicy(
            site_key=row["site_key"],
            url_allow_prefixes=list(prefixes),
            min_interval_sec=row["min_interval_sec"],
            max_concurrency=row["max_concurrency"],
        )

    # ---- tasks ----

    def add_task(
        self,
        name: str,
        account_id: int,
        script: str,
        schedule: str,
        params_json: str = "{}",
        max_retries: int = 2,
        timeout_sec: int = 120,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks
                  (name, account_id, script, schedule, params_json,
                   max_retries, timeout_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    account_id,
                    script,
                    schedule,
                    params_json,
                    max_retries,
                    timeout_sec,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_task(self, id: int) -> Optional[Task]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (id,)).fetchone()
        return self._row_to_task(row) if row else None

    def get_task_by_name(self, name: str) -> Optional[Task]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE name = ?", (name,)
            ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self) -> list[Task]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [self._row_to_task(r) for r in rows]

    def set_task_enabled(self, id: int, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, id),
            )
            conn.commit()

    def touch_task_started(self, id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET last_started_at = ? WHERE id = ?",
                (_now(), id),
            )
            conn.commit()

    def list_due_tasks(self) -> list[Task]:
        """Return enabled tasks whose interval schedule is due.

        Due if last_started_at is empty/NULL, or age >= N seconds for schedule
        of form interval:N. Non-interval schedules are ignored for now.
        """
        now = time.time()
        due: list[Task] = []
        for t in self.list_tasks():
            if not t.enabled:
                continue
            if not t.schedule.startswith("interval:"):
                continue
            try:
                n = int(t.schedule.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
            if not t.last_started_at:
                due.append(t)
                continue
            try:
                # Parse time.strftime("%Y-%m-%dT%H:%M:%S")
                started = time.mktime(
                    time.strptime(t.last_started_at, "%Y-%m-%dT%H:%M:%S")
                )
            except ValueError:
                due.append(t)
                continue
            if now - started >= n:
                due.append(t)
        return due

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            name=row["name"],
            account_id=row["account_id"],
            script=row["script"],
            schedule=row["schedule"],
            enabled=bool(row["enabled"]),
            max_retries=row["max_retries"],
            timeout_sec=row["timeout_sec"],
            params_json=row["params_json"],
            last_started_at=row["last_started_at"],
        )

    # ---- task runs ----

    def start_task_run(self, task_id: int) -> int:
        started = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_runs (task_id, started_at, status)
                VALUES (?, ?, ?)
                """,
                (task_id, started, "running"),
            )
            conn.execute(
                "UPDATE tasks SET last_started_at = ? WHERE id = ?",
                (started, task_id),
            )
            conn.commit()
            return int(cur.lastrowid)

    def finish_task_run(
        self,
        run_id: int,
        status: str,
        error: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET finished_at = ?, status = ?, error = ?, log_path = ?
                WHERE id = ?
                """,
                (_now(), status, error, log_path, run_id),
            )
            conn.commit()

    def list_recent_runs(self, limit: int = 20) -> list[TaskRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_task_run(r) for r in rows]

    @staticmethod
    def _row_to_task_run(row: sqlite3.Row) -> TaskRun:
        return TaskRun(
            id=row["id"],
            task_id=row["task_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            error=row["error"],
            log_path=row["log_path"],
        )
