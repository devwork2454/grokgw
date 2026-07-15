"""Validate that AGENTS.md verification command works as documented.

Locks the contract: any agent following AGENTS.md must hit the documented
success path for "installing + verifying DrissionPage 5.0.0b0 from local source".
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ANTIBOT = REPO / 'antibot'

# Exact command documented in AGENTS.md
VERIFY_CMD = (
    "from DrissionPage import Chromium; "
    "assert Chromium.__module__ == 'DrissionPage._browsers.chromium', 'wrong source'; "
    "assert 'latest_tab' in dir(Chromium), 'wrong API (need 5.x with latest_tab)'; "
    "import DrissionPage; "
    "assert DrissionPage.__file__ and 'DrissionPage/DrissionPage/__init__.py' in DrissionPage.__file__, 'wrong source'; "
    "print('OK 5.0.0b0:', DrissionPage.__file__)"
)


def test_agents_md_verification_command_runs():
    """The exact command in AGENTS.md must succeed from the venv."""
    proc = subprocess.run(
        ['bash', '-c', f'source {ANTIBOT}/.venv/bin/activate && python -c "{VERIFY_CMD}"'],
        capture_output=True, text=True, timeout=30,
        cwd=str(ANTIBOT),
    )
    assert proc.returncode == 0, (
        f"AGENTS.md verification command failed\nexit={proc.returncode}\n"
        f"stderr={proc.stderr}\nstdout={proc.stdout}"
    )
    assert 'OK 5.0.0b0' in proc.stdout, (
        f"missing OK marker — was the assertion stripped?\nstdout={proc.stdout!r}"
    )
    assert 'DrissionPage/DrissionPage/__init__.py' in proc.stdout


def test_agents_md_run_scripts_have_headless_workaround():
    """AGENTS.md '5.0.0b0 attach bug' section mandates .headless(True) workaround."""
    for name in ('run_takeover.py', 'run_monitor.py'):
        text = (ANTIBOT / name).read_text()
        assert '.headless(True)' in text, (
            f"{name} missing .headless(True) workaround — see AGENTS.md bug section"
        )


if __name__ == '__main__':
    failures = []
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except (AssertionError, Exception) as e:
                failures.append((name, str(e)))
                print(f'FAIL {name}: {e}')
    if failures:
        print(f'\n{len(failures)} failure(s)')
        sys.exit(1)
