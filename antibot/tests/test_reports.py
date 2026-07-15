"""Validate report JSON artifacts produced by antibot scripts.

Pins the current observable behavior so regressions are caught:
- baseline user-agent row FAILS (HeadlessChrome in UA)
- hardened user-agent row PASSES (stealth_min.js rewrites UA)
- hardened UA string contains 'Chrome' and NOT 'HeadlessChrome'
- hardened fingerprint webdriver is False
- monitor_run catches cf-turnstile on nowsecure

Run from any cwd; pytest discovers this via the antibot/tests/ layout.
"""
import json
import sys
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent.parent / 'report'


def _load(name):
    p = REPORT_DIR / name
    assert p.exists(), f"{p} not found — run the antibot scripts first"
    return json.loads(p.read_text(encoding='utf-8'))


def test_baseline_is_list_of_one():
    data = _load('detect_result.json')
    assert isinstance(data, list), "baseline should be a list (run_detect2 format)"
    assert len(data) == 1


def test_baseline_user_agent_fails():
    """HeadlessChrome in UA → row must be failed."""
    data = _load('detect_result.json')
    site = data[0]['sites']['sannysoft']
    assert 'user-agent' in site['items'], "user-agent row must exist in baseline"
    assert site['items']['user-agent']['passed'] is False, (
        f"baseline UA should fail; got {site['items']['user-agent']}"
    )


def test_hardened_user_agent_passes():
    """stealth_min.js rewrites UA → row must be passed."""
    data = _load('detect_result_hardened.json')
    site = data[0]['sannysoft']
    assert 'user-agent' in site['items']
    assert site['items']['user-agent']['passed'] is True, (
        f"hardened UA should pass; got {site['items']['user-agent']}"
    )


def test_hardened_ua_no_headless():
    """UA string must contain 'Chrome' but NOT 'HeadlessChrome'."""
    data = _load('detect_result_hardened.json')
    ua = data[0]['fingerprint']['userAgent']
    assert 'Chrome' in ua, f"UA missing Chrome: {ua}"
    assert 'HeadlessChrome' not in ua, f"UA still has HeadlessChrome: {ua}"


def test_hardened_webdriver_false():
    data = _load('detect_result_hardened.json')
    assert data[0]['fingerprint']['webdriver'] is False


def test_hardened_cdc_props_empty():
    """DrissionPage shouldn't expose $cdc/$wdc injection (Selenium giveaway)."""
    data = _load('detect_result_hardened.json')
    assert data[0]['fingerprint']['cdc_props'] == []


def test_hardened_all_items_pass():
    """Every item that DID render must pass (UA fix complete)."""
    data = _load('detect_result_hardened.json')
    site = data[0]['sannysoft']
    failed = site.get('failed_items', [])
    assert failed == [], f"hardened has failed items: {failed}"
    assert site['passed'] == site['total'], (
        f"passed={site['passed']} != total={site['total']} — items present must all pass"
    )


def test_monitor_nowsecure_has_captcha_alerts():
    """C/nowsecure should trip at least one captcha_element alert."""
    data = _load('monitor_result.json')
    assert data['nowsecure_alerts'] >= 1, (
        f"nowsecure should trigger alerts; got nowsecure_alerts={data['nowsecure_alerts']}"
    )


if __name__ == '__main__':
    # Allow running without pytest installed
    failures = []
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as e:
                failures.append((name, str(e)))
                print(f'FAIL {name}: {e}')
            except Exception as e:
                failures.append((name, repr(e)))
                print(f'ERROR {name}: {e!r}')
    if failures:
        print(f'\n{len(failures)} failure(s)')
        sys.exit(1)
    print(f'\nall {sum(1 for n,_ in [(n, None) for n in globals() if n.startswith("test_") if callable(globals()[n])])} passed')
