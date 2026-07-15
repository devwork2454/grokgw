"""argparse CLI for browser-ops runtime (doctor / proxy / account / policy / task / status / run / session / regress)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from runtime import paths
from runtime.store import Store


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _store() -> Store:
    s = Store()
    s.init_db()
    return s


def _tcp_ok(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def cmd_doctor(_args: argparse.Namespace) -> int:
    chrome = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if chrome:
        _ok(f"chrome={chrome}")
    else:
        _fail("chrome=not found (google-chrome/chromium/chromium-browser)")

    # Repo-root folder DrissionPage/ can shadow the editable install when CWD is
    # on sys.path; drop empty/CWD entries for a clean import check.
    ok_dp = False
    saved_path = list(sys.path)
    try:
        sys.path = [p for p in sys.path if p not in ("", os.getcwd())]
        # Drop any partial import from a prior namespace shadow.
        for key in list(sys.modules):
            if key == "DrissionPage" or key.startswith("DrissionPage."):
                del sys.modules[key]
        from DrissionPage import Chromium

        mod = Chromium.__module__
        ok_dp = "chromium" in mod
        if ok_dp:
            _ok(f"DrissionPage module={mod}")
        else:
            _fail(f"DrissionPage module={mod} (expected path containing 'chromium')")
    except Exception as e:
        _fail(f"DrissionPage import failed: {e}")
    finally:
        sys.path = saved_path

    if _tcp_ok("127.0.0.1", 2080):
        _ok("socks/proxy 127.0.0.1:2080")
    else:
        _fail("socks/proxy 127.0.0.1:2080 unreachable")

    try:
        paths.ensure_data_dirs()
        for p in (paths.DATA, paths.PROFILES, paths.SECRETS, paths.LOGS):
            if not os.access(p, os.W_OK):
                raise OSError(f"not writable: {p}")
        _ok(f"data dirs writable under {paths.DATA}")
    except OSError as e:
        _fail(f"data dirs: {e}")

    return 0 if (chrome and ok_dp) else 1


def cmd_proxy_add(args: argparse.Namespace) -> int:
    store = _store()
    if store.get_proxy_by_name(args.name):
        print(f"proxy already exists: {args.name}", file=sys.stderr)
        return 1
    pid = store.add_proxy(
        name=args.name,
        scheme=args.scheme,
        host=args.host,
        port=args.port,
    )
    print(f"proxy id={pid} name={args.name} {args.scheme}://{args.host}:{args.port}")
    return 0


def cmd_proxy_list(_args: argparse.Namespace) -> int:
    store = _store()
    rows = store.list_proxies()
    if not rows:
        print("(no proxies)")
        return 0
    print(f"{'id':>4}  {'name':<16}  {'url':<36}  {'health':<10}  last_check")
    for p in rows:
        print(
            f"{p.id:>4}  {p.name:<16}  {p.proxy_url():<36}  {p.health:<10}  "
            f"{p.last_check_at or '-'}"
        )
    return 0


def cmd_proxy_check(args: argparse.Namespace) -> int:
    store = _store()
    p = store.get_proxy_by_name(args.name)
    if not p:
        print(f"unknown proxy: {args.name}", file=sys.stderr)
        return 1
    ok = _tcp_ok(p.host, p.port)
    health = "ok" if ok else "bad"
    store.set_proxy_health(p.id, health)
    tag = "OK" if ok else "FAIL"
    print(f"[{tag}] proxy {p.name} {p.host}:{p.port} health={health}")
    return 0 if ok else 1


def cmd_account_add(args: argparse.Namespace) -> int:
    store = _store()
    if store.get_account_by_name(args.name):
        print(f"account already exists: {args.name}", file=sys.stderr)
        return 1

    proxy_id: Optional[int] = None
    if args.proxy_name:
        px = store.get_proxy_by_name(args.proxy_name)
        if not px:
            print(f"unknown proxy: {args.proxy_name}", file=sys.stderr)
            return 1
        proxy_id = px.id

    secret_ref: Optional[str] = args.secret_ref
    if args.password is not None:
        paths.ensure_data_dirs()
        secret_path = paths.SECRETS / args.name
        secret_path.write_text(args.password, encoding="utf-8")
        os.chmod(secret_path, 0o600)
        secret_ref = str(secret_path)
    elif secret_ref:
        # If user points at a path that exists, leave it; if creating empty ref file, secure it.
        sp = Path(secret_ref)
        if not sp.is_absolute():
            sp = paths.SECRETS / secret_ref
            secret_ref = str(sp)
        if not sp.exists():
            paths.ensure_data_dirs()
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.touch()
            os.chmod(sp, 0o600)

    aid = store.add_account(
        name=args.name,
        site_key=args.site_key,
        username=args.username,
        proxy_id=proxy_id,
        secret_ref=secret_ref,
    )
    print(
        f"account id={aid} name={args.name} site_key={args.site_key} "
        f"proxy_id={proxy_id} secret_ref={secret_ref or '-'}"
    )
    return 0


def cmd_account_list(_args: argparse.Namespace) -> int:
    store = _store()
    rows = store.list_accounts()
    if not rows:
        print("(no accounts)")
        return 0
    print(
        f"{'id':>4}  {'name':<16}  {'site_key':<16}  {'status':<10}  "
        f"{'proxy_id':>8}  username"
    )
    for a in rows:
        print(
            f"{a.id:>4}  {a.name:<16}  {a.site_key:<16}  {a.status:<10}  "
            f"{a.proxy_id if a.proxy_id is not None else '-':>8}  {a.username or '-'}"
        )
    return 0


def cmd_policy_set(args: argparse.Namespace) -> int:
    store = _store()
    store.set_policy(
        site_key=args.site_key,
        prefixes=list(args.allow),
        min_interval_sec=args.min_interval,
        max_concurrency=args.max_concurrency,
    )
    print(
        f"policy site_key={args.site_key} allow={args.allow} "
        f"min_interval={args.min_interval} max_concurrency={args.max_concurrency}"
    )
    return 0


def cmd_policy_show(args: argparse.Namespace) -> int:
    store = _store()
    pol = store.get_policy(args.site_key)
    if not pol:
        print(f"no policy for site_key={args.site_key}")
        return 1
    print(f"site_key:        {pol.site_key}")
    print(f"allow_prefixes:  {pol.url_allow_prefixes}")
    print(f"min_interval:    {pol.min_interval_sec}")
    print(f"max_concurrency: {pol.max_concurrency}")
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    store = _store()
    if store.get_task_by_name(args.name):
        print(f"task already exists: {args.name}", file=sys.stderr)
        return 1
    acct = store.get_account_by_name(args.account)
    if not acct:
        print(f"unknown account: {args.account}", file=sys.stderr)
        return 1

    params: dict[str, str] = {}
    for item in args.param or []:
        if "=" not in item:
            print(f"invalid --param (need key=val): {item}", file=sys.stderr)
            return 1
        k, v = item.split("=", 1)
        params[k] = v

    schedule = f"interval:{args.interval}"
    params_json = json.dumps(params, ensure_ascii=False)
    tid = store.add_task(
        name=args.name,
        account_id=acct.id,
        script=args.script,
        schedule=schedule,
        params_json=params_json,
    )
    print(
        f"task id={tid} name={args.name} account={args.account} "
        f"script={args.script} schedule={schedule} params={params_json}"
    )
    return 0


def cmd_task_list(_args: argparse.Namespace) -> int:
    store = _store()
    rows = store.list_tasks()
    if not rows:
        print("(no tasks)")
        return 0
    print(
        f"{'id':>4}  {'name':<16}  {'account_id':>10}  {'enabled':<8}  "
        f"{'schedule':<16}  script"
    )
    for t in rows:
        print(
            f"{t.id:>4}  {t.name:<16}  {t.account_id:>10}  "
            f"{str(t.enabled):<8}  {t.schedule:<16}  {t.script}"
        )
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    store = _store()
    print("=== accounts ===")
    accounts = store.list_accounts()
    if not accounts:
        print("(no accounts)")
    else:
        for a in accounts:
            print(
                f"  [{a.id}] {a.name} site={a.site_key} status={a.status} "
                f"fail_streak={a.fail_streak} last_ok={a.last_ok_at or '-'} "
                f"last_error={a.last_error or '-'}"
            )

    print("=== recent runs ===")
    runs = store.list_recent_runs(limit=20)
    if not runs:
        print("(no runs)")
    else:
        for r in runs:
            print(
                f"  run={r.id} task_id={r.task_id} status={r.status} "
                f"started={r.started_at} finished={r.finished_at or '-'} "
                f"error={r.error or '-'}"
            )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from runtime.scheduler import run_loop, run_once

    store = _store()
    if args.once:
        return run_once(store, args.once)
    # --loop
    run_loop(store, tick_sec=args.tick)
    return 0


def cmd_session_login(args: argparse.Namespace) -> int:
    """Seed or wait on an account profile.

    True interactive login needs a display or remote-debug forwarding (P1).
    Headless mode supports session seeding via --seed-js (cookie/localStorage)
    and optional --url + --wait-sec before closing and persisting the profile.
    """
    from runtime.risk import url_allowed
    from runtime.session import SessionManager

    store = _store()
    acc = store.get_account_by_name(args.account)
    if not acc:
        print(f"unknown account: {args.account}", file=sys.stderr)
        return 1
    if acc.proxy_id is None:
        print(f"account has no proxy: {args.account}", file=sys.stderr)
        return 1
    proxy = store.get_proxy(acc.proxy_id)
    if not proxy:
        print(f"proxy id={acc.proxy_id} missing for account {args.account}", file=sys.stderr)
        return 1

    policy = store.get_policy(acc.site_key)
    sm = SessionManager()
    sess, lock = sm.open(acc, proxy, stealth=True)
    try:
        print(
            f"Profile ready on port {sess.port}. "
            "Complete login in this headless session is limited."
        )
        if args.url:
            prefixes = policy.url_allow_prefixes if policy else []
            if not url_allowed(args.url, prefixes):
                print(f"url not allowlisted: {args.url}", file=sys.stderr)
                return 1
            sess.tab.get(args.url)
        if args.seed_js:
            sess.tab.run_js(args.seed_js)
        time.sleep(args.wait_sec)
        print(f"session saved under {acc.profile_path}")
        return 0
    finally:
        sm.close(sess, lock)


def cmd_regress(args: argparse.Namespace) -> int:
    """Run antibot regression scripts without touching operational profiles."""
    antibot = paths.ROOT / "antibot"
    before = set(p.name for p in paths.PROFILES.glob("*")) if paths.PROFILES.exists() else set()
    if args.what == "detect":
        cmd = [sys.executable, str(antibot / "run_takeover.py"), "hardened"]
    else:
        cmd = [sys.executable, str(antibot / "run_monitor.py")]
    print("running", cmd)
    r = subprocess.run(cmd, cwd=str(antibot))
    after = set(p.name for p in paths.PROFILES.glob("*")) if paths.PROFILES.exists() else set()
    new_entries = after - before
    if new_entries:
        print("FAIL: regress mutated data/profiles:", new_entries)
        return 1
    return int(r.returncode)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runtime", description="browser-ops runtime CLI")
    sub = p.add_subparsers(dest="command", required=True)

    # doctor
    sp = sub.add_parser("doctor", help="environment health checks")
    sp.set_defaults(func=cmd_doctor)

    # proxy
    px = sub.add_parser("proxy", help="proxy management")
    px_sub = px.add_subparsers(dest="proxy_cmd", required=True)

    pa = px_sub.add_parser("add", help="add a proxy")
    pa.add_argument("--name", required=True)
    pa.add_argument("--host", required=True)
    pa.add_argument("--port", type=int, required=True)
    pa.add_argument("--scheme", default="socks5")
    pa.set_defaults(func=cmd_proxy_add)

    pl = px_sub.add_parser("list", help="list proxies")
    pl.set_defaults(func=cmd_proxy_list)

    pc = px_sub.add_parser("check", help="TCP-check a proxy and update health")
    pc.add_argument("--name", required=True)
    pc.set_defaults(func=cmd_proxy_check)

    # account
    ac = sub.add_parser("account", help="account management")
    ac_sub = ac.add_subparsers(dest="account_cmd", required=True)

    aa = ac_sub.add_parser("add", help="add an account")
    aa.add_argument("--name", required=True)
    aa.add_argument("--site-key", required=True, dest="site_key")
    aa.add_argument("--username", default=None)
    aa.add_argument("--proxy-name", default=None, dest="proxy_name")
    aa.add_argument("--secret-ref", default=None, dest="secret_ref")
    aa.add_argument("--password", default=None, help="write to data/secrets/<name> (0o600)")
    aa.set_defaults(func=cmd_account_add)

    al = ac_sub.add_parser("list", help="list accounts")
    al.set_defaults(func=cmd_account_list)

    # policy
    po = sub.add_parser("policy", help="site policy management")
    po_sub = po.add_subparsers(dest="policy_cmd", required=True)

    ps = po_sub.add_parser("set", help="set/upsert site policy")
    ps.add_argument("--site-key", required=True, dest="site_key")
    ps.add_argument("--allow", nargs="+", required=True, metavar="PREFIX")
    ps.add_argument("--min-interval", type=int, default=0, dest="min_interval")
    ps.add_argument("--max-concurrency", type=int, default=1, dest="max_concurrency")
    ps.set_defaults(func=cmd_policy_set)

    psh = po_sub.add_parser("show", help="show site policy")
    psh.add_argument("--site-key", required=True, dest="site_key")
    psh.set_defaults(func=cmd_policy_show)

    # task
    tk = sub.add_parser("task", help="task management")
    tk_sub = tk.add_subparsers(dest="task_cmd", required=True)

    ta = tk_sub.add_parser("add", help="add a scheduled task")
    ta.add_argument("--name", required=True)
    ta.add_argument("--account", required=True, help="account name")
    ta.add_argument("--script", required=True)
    ta.add_argument("--interval", type=int, required=True, metavar="SEC")
    ta.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="key=val",
        help="task param (repeatable)",
    )
    ta.set_defaults(func=cmd_task_add)

    tl = tk_sub.add_parser("list", help="list tasks")
    tl.set_defaults(func=cmd_task_list)

    # status
    st = sub.add_parser("status", help="accounts + recent runs")
    st.set_defaults(func=cmd_status)

    # run
    rn = sub.add_parser("run", help="execute tasks once or in a loop")
    rn_mode = rn.add_mutually_exclusive_group(required=True)
    rn_mode.add_argument(
        "--once",
        metavar="TASK_NAME",
        help="run a single task by name (with retries)",
    )
    rn_mode.add_argument(
        "--loop",
        action="store_true",
        help="poll due tasks forever",
    )
    rn.add_argument(
        "--tick",
        type=float,
        default=5.0,
        metavar="SEC",
        help="loop sleep between ticks (default 5.0)",
    )
    rn.set_defaults(func=cmd_run)

    # session
    se = sub.add_parser("session", help="session / profile operations")
    se_sub = se.add_subparsers(dest="session_cmd", required=True)

    sl = se_sub.add_parser(
        "login",
        help="open account profile for session seed / wait",
        description=(
            "Open the account Chrome profile (via bound proxy) for session seeding. "
            "True interactive login needs a display or remote-debug forwarding (P1). "
            "On this headless host, use --seed-js to write cookie/localStorage markers "
            "and optionally --url (allowlisted) + --wait-sec before the profile is saved."
        ),
    )
    sl.add_argument("account", help="account name")
    sl.add_argument("--url", default=None, help="navigate after open (must be allowlisted)")
    sl.add_argument(
        "--seed-js",
        default=None,
        dest="seed_js",
        help="JS to run after navigate (e.g. localStorage seed for headless)",
    )
    sl.add_argument(
        "--wait-sec",
        type=float,
        default=5.0,
        dest="wait_sec",
        metavar="N",
        help="seconds to wait before close (default 5)",
    )
    sl.set_defaults(func=cmd_session_login)

    # regress
    rg = sub.add_parser(
        "regress",
        help="run antibot regression (detect|monitor); must not create data/profiles entries",
    )
    rg.add_argument(
        "what",
        choices=["detect", "monitor"],
        help="detect → run_takeover.py hardened; monitor → run_monitor.py",
    )
    rg.set_defaults(func=cmd_regress)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
