# runtime/scheduler.py
from __future__ import annotations

import time
from typing import Optional

from runtime.risk import RiskGate
from runtime.runner import execute_task
from runtime.session import SessionManager
from runtime.store import Store


def run_once(store: Store, task_name: str, risk: Optional[RiskGate] = None) -> int:
    risk = risk or RiskGate()
    sm = SessionManager()
    task = store.get_task_by_name(task_name)
    if not task:
        print(f"unknown task {task_name}")
        return 2
    # simple retry loop
    attempt = 0
    while True:
        attempt += 1
        result = execute_task(store, risk, sm, task)
        if result.ok:
            print(f"OK {task_name}: {result.message}")
            return 0
        if result.message.startswith("skipped:"):
            print(f"SKIP {task_name}: {result.message}")
            return 0
        if result.retryable and attempt <= task.max_retries:
            time.sleep(min(2 ** attempt, 30))
            continue
        print(f"FAIL {task_name}: {result.message}")
        return 1


def run_loop(
    store: Store, risk: Optional[RiskGate] = None, tick_sec: float = 5.0
) -> None:
    risk = risk or RiskGate()
    sm = SessionManager()
    print("scheduler loop started")
    while True:
        for task in store.list_due_tasks():
            execute_task(store, risk, sm, task)
        time.sleep(tick_sec)
