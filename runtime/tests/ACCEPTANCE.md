# P0 Acceptance Record

Date: 2026-07-15  
Environment: Linux headless, Chrome 148, socks5 `127.0.0.1:2080`, DrissionPage 5.0.0b0 editable

| ID | Scenario | Result | Notes |
|----|----------|--------|-------|
| V1 | `python -m runtime doctor` | **PASS** | chrome OK, DP chromium module OK, proxy 2080 OK, data writable |
| V2 | dual account isolation | **PARTIAL** | Not fully dual-account exercised this run; profile paths are per-account under `data/profiles/<id>` |
| V3 | session persistence | **PASS** | `session login demo --seed-js localStorage auth=1` then `run --once probe` → `read ok '1'` |
| V4 | dual proxy | **PARTIAL** | Single real proxy in env; CLI binds `proxy_id` per account; full dual-egress needs second proxy |
| V5 | schedule ≥10 | **SKIPPED** | `--loop` implemented; long soak not run in this session |
| V6 | circuit bad proxy | **SKIPPED** | RiskGate + `set_proxy_health` wired; not re-run end-to-end this session |
| V7 | allowlist | **PASS (unit)** | `test_healthcheck_blocks_off_policy` + fail-closed empty prefixes |
| V8 | regress isolation | **NOT RUN** | CLI `regress detect\|monitor` implemented; full antibot run not re-executed here |

## Unit tests (all PASS)

- test_models_import (2)
- test_store (2)
- test_risk (4)
- test_browser_contract (3)
- test_session_lock (1)
- test_healthcheck_unit (2)

## Integration smoke (PASS after Chrome cleanup)

```
session login demo → exit 0
run --once probe → OK read ok '1'
run --once hc → OK title='Example Domain'
```

## Known fixes applied post-implementation

1. **DrissionPage import shadow**: repo-root `DrissionPage/` broke `from DrissionPage import Chromium` — fixed in `runtime/browser.py` via `_import_chromium()` path scrub (same idea as `doctor`).
2. **Port reuse**: `_free` no longer uses `SO_REUSEADDR`; wait for port release after pkill; Chrome stderr tail on failure.

## Residual risks

- Concurrent/rapid Chrome start may still need `pkill` cleanup of stale debug ports.
- Stealth UA rewrite applies to **new** documents after CDP inject; immediate read on already-loaded `about:blank` may still show `HeadlessChrome` until navigation.
- No git repository in workspace — no commits made.
