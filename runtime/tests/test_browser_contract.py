from pathlib import Path

from runtime.browser import BrowserRuntime  # noqa: F401 — import contract
from runtime.ports import acquire_port, release_port, _in_use, _PORT_MIN, _PORT_MAX


def test_browser_module_source_has_headless_workaround():
    src = Path(__file__).resolve().parents[1] / "browser.py"
    text = src.read_text(encoding="utf-8")
    assert ".headless(True)" in text
    assert "set_address" in text
    assert "5.0.0b0" in text


def test_stealth_path_points_to_antibot():
    from runtime.paths import STEALTH_MIN_JS

    assert STEALTH_MIN_JS.name == "stealth_min.js"
    assert STEALTH_MIN_JS.parent.name == "antibot"


def test_acquire_release_port_roundtrip():
    port = acquire_port()
    try:
        assert _PORT_MIN <= port <= _PORT_MAX
        assert port in _in_use
        # same port stays reserved while in use
        port2 = acquire_port()
        assert port2 != port
        release_port(port2)
    finally:
        release_port(port)
    assert port not in _in_use
