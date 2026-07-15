from __future__ import annotations

import importlib
import json
from typing import Callable

from runtime.audit import audit
from runtime.models import Result, RunContext, Task
from runtime.risk import RiskGate
from runtime.session import SessionManager
from runtime.store import Store


def load_task_callable(script: str) -> Callable:
    mod = importlib.import_module(script)
    if not hasattr(mod, "run"):
        raise RuntimeError(f"{script} has no run(ctx)")
    return mod.run


def execute_task(
    store: Store,
    risk: RiskGate,
    session_mgr: SessionManager,
    task: Task,
    *,
    stealth: bool = True,
) -> Result:
    account = store.get_account(task.account_id)
    if account is None:
        return Result(ok=False, message=f"account not found: {task.account_id}")
    proxy = store.get_proxy(account.proxy_id) if account.proxy_id else None
    policy = store.get_policy(account.site_key)

    decision = risk.can_run(task, account, proxy, policy)
    if not decision.allowed:
        rid = store.start_task_run(task.id)
        store.finish_task_run(rid, status="skipped_circuit", error=decision.reason)
        audit(
            "task_skipped",
            task=task.name,
            account=account.name,
            reason=decision.reason,
        )
        return Result(ok=False, message=f"skipped:{decision.reason}")

    risk.mark_start(account)
    rid = store.start_task_run(task.id)
    store.touch_task_started(task.id)
    sess = None
    lock = None
    try:
        sess, lock = session_mgr.open(account, proxy, stealth=stealth)
        params = json.loads(task.params_json or "{}")
        prefixes = policy.url_allow_prefixes if policy else []
        ctx = RunContext(
            tab=sess.tab,
            account=account,
            params=params,
            logger=None,
            allowed_prefixes=prefixes,
        )
        fn = load_task_callable(task.script)
        result: Result = fn(ctx)
        status = "ok" if result.ok else "fail"
        store.finish_task_run(rid, status=status, error=result.message or None)
        if result.ok:
            store.clear_fail_streak(account.id)
        else:
            store.bump_fail_streak(account.id)
            if result.need_relogin:
                store.update_account_status(
                    account.id, "need_relogin", result.message
                )
        audit(
            "task_done",
            task=task.name,
            account=account.name,
            ok=result.ok,
            message=result.message,
        )
        return result
    except Exception as e:
        store.finish_task_run(rid, status="fail", error=str(e))
        store.bump_fail_streak(account.id)
        audit("task_error", task=task.name, account=account.name, error=str(e))
        return Result(ok=False, retryable=True, message=str(e))
    finally:
        if sess is not None and lock is not None:
            session_mgr.close(sess, lock)
        risk.mark_end(account)
