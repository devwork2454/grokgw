from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from runtime import paths
from runtime.ports import acquire_port, release_port


def _import_chromium():
    """Import Chromium from the editable 5.x install, not the repo-root shadow folder.

    Repo root contains ``DrissionPage/`` source tree; with CWD on ``sys.path``,
    ``import DrissionPage`` resolves to a broken namespace and has no Chromium.
    """
    saved = list(sys.path)
    root = str(paths.ROOT)
    sys.path = [p for p in sys.path if p not in ("", os.getcwd(), root)]
    for key in list(sys.modules):
        if key == "DrissionPage" or key.startswith("DrissionPage."):
            del sys.modules[key]
    try:
        from DrissionPage import Chromium, ChromiumOptions

        return Chromium, ChromiumOptions
    finally:
        sys.path = saved


def wait_port(port: int, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@dataclass
class BrowserSession:
    port: int
    proc: subprocess.Popen
    browser: object  # Chromium
    tab: object
    profile_dir: Path
    ephemeral: bool


class BrowserRuntime:
    def start(
        self,
        profile_dir: Path,
        proxy_url: str,
        *,
        stealth: bool = True,
        ephemeral: bool = False,
    ) -> BrowserSession:
        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        port = acquire_port()
        # 清理同端口残留（精确匹配，避免误杀）
        subprocess.run(
            ["pkill", "-9", "-f", f"remote-debugging-port={port}"],
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
        # wait until OS actually releases the port
        deadline = time.time() + 10
        while time.time() < deadline:
            from runtime.ports import _free

            if _free(port):
                break
            time.sleep(0.2)
        err_log = profile_dir / f"chrome-{port}.stderr.log"
        cmd = [
            "google-chrome",
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--proxy-server={proxy_url}",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={str(profile_dir)}",
            "about:blank",
        ]
        err_fh = open(err_log, "w")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err_fh)
        if not wait_port(port, 30):
            try:
                proc.kill()
            except Exception:
                pass
            try:
                err_fh.close()
            except Exception:
                pass
            release_port(port)
            tail = ""
            try:
                tail = err_log.read_text(encoding="utf-8", errors="replace")[-800:]
            except Exception:
                pass
            raise RuntimeError(f"Chrome port {port} not ready; stderr tail:\n{tail}")
        try:
            err_fh.close()
        except Exception:
            pass
        # 5.0.0b0 attach bug: must set .headless(True) so _is_headless matches HeadlessChrome
        # Otherwise Chromium.__init__ triggers quit+reconnect and hangs ~30s
        Chromium, ChromiumOptions = _import_chromium()

        browser = Chromium(ChromiumOptions().set_address(f"127.0.0.1:{port}").headless(True))
        tab = browser.latest_tab
        if stealth:
            js = paths.STEALTH_MIN_JS.read_text(encoding="utf-8")
            tab.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=js)
        return BrowserSession(
            port=port,
            proc=proc,
            browser=browser,
            tab=tab,
            profile_dir=profile_dir,
            ephemeral=ephemeral,
        )

    def stop(self, session: BrowserSession) -> None:
        try:
            # best-effort
            if hasattr(session.browser, "quit"):
                session.browser.quit()
        except Exception:
            pass
        try:
            session.proc.terminate()
            session.proc.wait(timeout=5)
        except Exception:
            try:
                session.proc.kill()
            except Exception:
                pass
        subprocess.run(
            ["pkill", "-9", "-f", f"remote-debugging-port={session.port}"],
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        release_port(session.port)
        if session.ephemeral:
            import shutil

            shutil.rmtree(session.profile_dir, ignore_errors=True)
        # operational profiles: NEVER rmtree
