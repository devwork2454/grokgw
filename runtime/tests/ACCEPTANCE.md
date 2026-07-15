# P0 Acceptance Record

Date: 2026-07-15 (full re-run)  
Environment: Linux headless, Chrome 148, socks5 `127.0.0.1:2080`, DrissionPage 5.0.0b0 editable  
Machine results: `runtime/tests/acceptance_run.json`

| ID | Scenario | Result | Notes |
|----|----------|--------|-------|
| V1 | `python -m runtime doctor` | **PASS** | chrome / DP chromium / proxy 2080 / data writable |
| V2 | dual account isolation | **PASS** | `iso_a`/`iso_b` write MARK_A/MARK_B; own read OK; cross-read A expect MARK_B → got MARK_A (isolated) |
| V3 | session persistence | **PASS** | earlier: `session login` seed + `probe` read ok `'1'` |
| V4 | dual proxy | **PARTIAL** | Single real egress proxy in this host; `proxy_id` binding + dead proxy circuit covered by V6 |
| V5 | schedule ≥10 | **PASS** | 10/10 consecutive `soak_hc` successes (no port/profile clash) |
| V6 | circuit bad proxy | **PASS** | `bad_task` → `skipped_circuit` / `proxy_bad`; `soak_hc` on good proxy still OK |
| V7 | allowlist | **PASS** | unit: off-policy URL blocked; fail-closed empty prefixes |
| V8 | regress isolation | **PASS** | `regress detect` rc=0; **no new** `data/profiles/*`; sannysoft hardened 8/8 in lab |

## Unit tests

14/14 PASS (`test_models_import`, `test_store`, `test_risk`, `test_browser_contract`, `test_session_lock`, `test_healthcheck_unit`).

## Integration highlights (this run)

```
V2: write/read A+B OK; cross-read fails as expected
V5: soak_hc ×10 all OK
V6: SKIP bad_task: skipped:proxy_bad; good soak_hc OK
V8: regress detect → sannysoft 8/8, profiles unchanged
```

## Residual / environment notes

- V4 full dual-egress needs a second working proxy; not available on this host.
- Rapid Chrome restarts may need debug-port cleanup (`pkill` remote-debugging-port=96xx).
- Operational `data/` is gitignored (profiles, sqlite, secrets).

## Re-run sketch

```bash
cd /home/zakza/project/research/xpage
source antibot/.venv/bin/activate
ss -tlnp | grep 2080 || vpn
python -m runtime doctor
# then re-execute the V2/V5/V6/V8 sequence (or paste runner from session history)
```
