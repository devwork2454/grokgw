# AGENTS.md — xpage research workspace

This workspace is **research code, not a packaged application**. There is no build system, no linter, no formatter, no test runner, no CI. Two roots:

- `DrissionPage/` — local clone of the upstream library at **5.0.0b0** (beta, **not on PyPI**). Installed editable.
- `antibot/` — research scripts that use DrissionPage to probe bot-detection sites.

Do not add a build/lint/CI layer without an explicit request.

## DrissionPage version trap

- Local source is **5.0.0b0** with the new `Chromium` + `latest_tab` API.
- PyPI latest is **4.1.1.4** with a different (older) API — they are **not interchangeable**.
- Always install from local source **from inside the venv** (editable install is a namespace package; outside-venv imports can pick up the wrong path):
  ```bash
  cd antibot
  source .venv/bin/activate
  pip install -e ../DrissionPage
  ```
- Verify (5.0.0b0 has no `__version__` attribute — editable install uses a namespace finder):
  ```bash
  python -c "from DrissionPage import Chromium; \
    assert Chromium.__module__ == 'DrissionPage._browsers.chromium', 'wrong source'; \
    assert 'latest_tab' in dir(Chromium), 'wrong API (need 5.x with latest_tab)'; \
    import DrissionPage; \
    assert DrissionPage.__file__ and 'DrissionPage/DrissionPage/__init__.py' in DrissionPage.__file__, 'wrong source'; \
    print('OK 5.0.0b0:', DrissionPage.__file__)"
  ```
  Should print `OK 5.0.0b0: /home/zakza/project/research/xpage/DrissionPage/DrissionPage/__init__.py`.
- Beta has real bugs. Do not paper over them; report them.

## Network / Chrome gotcha (critical)

This host has **broken IPv6 egress**. Cloudflare-hosted sites (`bot.sannysoft.com`, `nowsecure.nl`, etc.) DNS-resolve to IPv6-only and Chrome's Happy Eyeballs hangs forever.

**Always launch Chrome with the local socks5 proxy:**
```python
co.set_argument('--proxy-server=socks5://127.0.0.1:2080')
co.set_argument('--no-sandbox')
co.set_argument('--disable-gpu')
```

- `--no-proxy-server` and `--host-resolver-rules="AF ipv4"` do **not** fix it; they sometimes hang.
- Verify proxy is up: `ss -tlnp | grep 2080`. If not listening, the user must run `! vpn` in their own terminal.
- Diagnostic recipe and full history: see `~/.claude/projects/-home-zakza-project-research-xpage/memory/chrome-ipv6-and-system-proxy.md`.

## Recommended launch pattern: "接管模式" (takeover)

`DrissionPage` auto-managed Chromium launch occasionally hangs/fails on this host (esp. headless). The verified-stable pattern is **subprocess launch Chrome → DrissionPage attaches via CDP port**. See `antibot/run_takeover.py` and `antibot/run_monitor.py` for the working template.

Key elements:
- Spawn `google-chrome --headless=new --no-sandbox --disable-gpu --proxy-server=socks5://127.0.0.1:2080 --remote-debugging-port=<port> --user-data-dir=<tmpdir> about:blank`
- Wait on `http://127.0.0.1:<port>/json/version` until ready.
- `Chromium(f'127.0.0.1:{port}')` then `b.latest_tab`.
- Always `pkill -9 -f remote-debugging-port=<port>` and `shutil.rmtree(user_dir)` between runs to avoid profile lock contention.

## 5.0.0b0-specific bug: `set_user_agent` breaks headless

`ChromiumOptions.set_user_agent()` in headless mode causes Chrome to fail to start under 5.0.0b0.

**Workaround (proven):** do not call `set_user_agent`. Patch the UA at runtime via `Page.addScriptToEvaluateOnNewDocument` using `Object.defineProperty(Navigator.prototype, 'userAgent', ...)`. See `antibot/stealth_min.js` for the minimal working patch (only rewrites UA when it contains `HeadlessChrome`, plus a defensive `webdriver=false`).

## Environment

- venv: `antibot/.venv` (Python 3.12). Already has local DrissionPage installed editable.
- Activate: `source antibot/.venv/bin/activate`
- Headless only — this is a display-less Linux box. "Headed" mode is unavailable; any test plan should not assume otherwise.
- Bash tool: long-running sessions may eventually fail to spawn Chrome subprocess (sandbox quirk). If `google-chrome --headless --dump-dom` starts returning exit 1 unexpectedly, switch to a new Bash session.

## Test sites used

| Site | URL | Notes |
|---|---|---|
| sannysoft | `https://bot.sannysoft.com` | Fingerprint checks; per-row result in `td[id$="-result"]`, className has `passed`/`failed` |
| nowsecure | `https://nowsecure.nl` | Anti-bot challenge page |
| pixelscan | `https://pixelscan.net` | Fingerprint detail |
| browserleaks | `https://browserleaks.com/javascript` | JS fingerprint |
| httpbin | `https://httpbin.org/status/{403,429,503,451}` | Reliable block-status code triggers for monitor validation |
| creepjs | `https://abrahamjuliot.github.io/creepjs/` | **Unreachable from this host** — skip |

Do not point any of these scripts at production sites or use real accounts. The plan in `.claude/plans/antibot_test_plan.md` is explicit about that.

## Antibot scripts — what's what

| File | Purpose |
|---|---|
| `run_takeover.py` | Detection run (baseline or hardened). Writes `report/detect_result.json` / `report/detect_result_hardened.json` + per-site full-page PNGs. Usage: `python run_takeover.py [hardened]` |
| `run_monitor.py` | Exercises `BotMonitor` on sannysoft / nowsecure / httpbin 403/429. Writes `report/monitor_result.json` + `report/alerts/*.json,*.png` |
| `monitor.py` | `BotMonitor` class — three detection modes (page-element selector match, response-body keyword match, status-code match on `tab.listen`) plus alert save + screenshot. Selector and keyword lists are hardcoded here; update them when adding new captcha/block patterns. |
| `hardened_options.py` | `build_hardened_extras()`, `build_hardened_user_agent()`, `apply_hardening(co)`. Note: `apply_hardening` calls `set_user_agent` — see bug note above; prefer injecting `stealth_min.js` via CDP instead. |
| `stealth_min.js` | Minimal safe stealth (UA rewrite + webdriver=false). **Use this by default.** |
| `stealth.js` | Aggressive full stealth (also touches plugins, languages, window.chrome, WebGL, CDC props). Riskier on real pages; only for fingerprint test beds. |
| `report/` | All run outputs land here. |
| `reports/summary.md` | Latest written test report — read this before re-running anything; it lists what was verified and what wasn't. |

## Fingerprint collection

When probing a site, the JS template in `run_takeover.py:collect_fingerprint()` is the canonical set: `navigator.webdriver`, `userAgent`, `languages`, `plugins.length`, `has window.chrome`, `chrome.runtime`, `cdc_props` (`document` keys starting with `$cdc`/`$wdc`), and `WEBGL_debug_renderer_info` vendor/renderer. On headless+no-GPU, WebGL is `no_webgl_context` — that's environmental, not a fingerprint fix.

## Current state (as of last run in `reports/summary.md`)

- **Baseline (no hardening):** sannysoft 8/11 pass. Fails: user-agent (`HeadlessChrome`), webgl-vendor/renderer (no GPU). `navigator.webdriver=false` and zero CDC props — strong baseline vs Selenium.
- **Hardening:** scripts ready (`run_takeover.py hardened`, `stealth_min.js`), expected to flip the user-agent row to passed.
- **Monitor framework:** scripts ready (`run_monitor.py`), all four test scenarios wired.
- **Run these in your own terminal** — the OpenCode Bash session where the baseline was measured cannot re-spawn Chrome subprocesses after long use. From the venv:
  ```bash
  cd antibot
  source .venv/bin/activate
  ss -tlnp | grep 2080 || vpn
  python run_takeover.py hardened
  python run_monitor.py
  ```

## Plan + report locations

- Test plan: `.claude/plans/antibot_test_plan.md`
- Latest report: `antibot/reports/summary.md`
- Persistent memory: `~/.claude/projects/-home-zakza-project-research-xpage/memory/chrome-ipv6-and-system-proxy.md`

## Browser Ops Runtime (P0)

- Package: `runtime/` — operational multi-account browser runtime (not antibot lab).
- Data: `data/` (gitignored) — sqlite, profiles, secrets, logs.
- Entry: from repo root with venv active:
  ```bash
  source antibot/.venv/bin/activate
  python -m runtime doctor
  python -m runtime run --once <task>
  python -m runtime run --loop
  python -m runtime regress detect
  ```
- Spec: `docs/superpowers/specs/2026-07-15-browser-ops-runtime-design.md`
- Plan: `docs/superpowers/plans/2026-07-15-browser-ops-runtime-p0.md`
- Never rmtree `data/profiles/*` operational dirs.
- Antibot scripts remain the fingerprint lab; prefer `runtime regress` for regression.

## Grok API Gateway (grokgw)

- Package: `grokgw/` - OpenAI-compatible local API gateway wrapping Grok Build CLI.
- Reuses SuperGrok subscription auth (`~/.grok/auth.json`), no API key needed.
- Entry: from repo root with venv active:
  ```bash
  source antibot/.venv/bin/activate
  python -m grokgw
  ```
- Spec: `docs/superpowers/specs/2026-07-15-grok-api-gateway-design.md`
- Plan: `docs/superpowers/plans/2026-07-15-grok-api-gateway.md`
- Each request runs `grok -p` in an isolated empty `/tmp` dir (avoids repo-upload privacy risk).
- No function calling; no multi-account token pool (M3+ evolution).
