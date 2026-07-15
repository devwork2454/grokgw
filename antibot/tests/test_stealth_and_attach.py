"""Validate the 5.0.0b0 attach bug workaround contract.

5.0.0b0 attach bug: ChromiumOptions must explicitly set .headless(True) when
attaching to a pre-launched Chrome via CDP, otherwise _is_headless desync
triggers quit+reconnect → 30s timeout.

These tests pin that contract without requiring a real Chrome session.
"""
import re
import sys
from pathlib import Path

ANTIBOT = Path(__file__).resolve().parent.parent


def _read(name):
    return (ANTIBOT / name).read_text()


def test_run_takeover_has_workaround():
    text = _read('run_takeover.py')
    assert '.headless(True)' in text, "run_takeover.py missing .headless(True) workaround"
    assert 'set_address(f' in text, "run_takeover.py must use set_address(...) not bare string"
    # bug context comment for future readers
    assert '5.0.0b0' in text and '_is_headless' in text, (
        "run_takeover.py needs a comment explaining the workaround for future agents"
    )


def test_run_monitor_has_workaround():
    text = _read('run_monitor.py')
    assert '.headless(True)' in text, "run_monitor.py missing .headless(True) workaround"
    assert '5.0.0b0' in text and '_is_headless' in text


def test_stealth_min_js_patches_headless():
    """stealth_min.js must rewrite UA when HeadlessChrome is present."""
    text = _read('stealth_min.js')
    assert 'HeadlessChrome' in text
    assert 'defineProperty' in text
    assert 'Navigator.prototype' in text and 'userAgent' in text


def test_stealth_min_js_disables_webdriver_defensively():
    """Even though CDP attach defaults webdriver=False, defend against it."""
    text = _read('stealth_min.js')
    assert 'webdriver' in text.lower()


if __name__ == '__main__':
    failures = []
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as e:
                failures.append((name, str(e)))
                print(f'FAIL {name}: {e}')
    if failures:
        print(f'\n{len(failures)} failure(s)')
        sys.exit(1)
