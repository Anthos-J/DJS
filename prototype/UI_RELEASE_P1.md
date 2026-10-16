# UI release P1: judge console on top of frozen engine E4.2.1

**Engine unchanged.** `mandate/engine_e421.py`, `mandate/state_e42.py`, `mandate/audit.py`, `config/*_e421.json` and the S2 Cedar policy still match `FROZEN_E421.sha256` (tag `engine-E4.2.1`, `7002aa1`). No historical evaluation record was changed.

## What changed

| Area | Files | Kind |
|---|---|---|
| Judge console (new) | `console/console.py`, `console/static/*` | New. Host-side, standard library only. UI, `/api` proxy, live scenarios, reset, recovery, diagnostics, results |
| Launcher (new) | `demo/launch.sh`, `demo/stop.sh` | New. Preflight, explicit `MANDATE_ENGINE=E4.2.1`, AM11 gates via `run_prototype.sh`, engine check, seed, console |
| Control-plane server | `control/server.py` | **Changed** (differs from `FROZEN_E421.sha256`). `/api/meta` now reports engine, recovery state, persistence and audit verification and counts. `POST /api/agents` accepts and validates `subjects` / `requester` (400 on invalid scope). No decision logic changed. |
| Compose | `compose.yaml` | **Changed** (differs from `FROZEN_E421.sha256`). Adds `MANDATE_RECOVERY: "${MANDATE_RECOVERY:-0}"` to the control service so the owner can start recovery mode. The default is unchanged (0); AM11 static and runtime gates pass. |
| Docs | `README_JUDGES.md`, `DEMO_SCRIPT.md`, `docs/architecture.svg`, `OWNER_REVIEW_CHECKLIST_E421.md`, `SUBMISSION_README.md` | New |
| Tests | `console/tests/test_console_integration.py` | New: 18 live tests |

Freeze of this release: `FROZEN_UI_P1.sha256`.

## Defects found and fixed during this release (all in new console code)

1. The console reset called WSL's `bash.exe` instead of Git Bash. The failing run is preserved at `console/tests/runs/20261016T180830`. Fix: the launcher passes `MANDATE_BASH`.
2. The HR-subjects field was visible for non-HR roles: a CSS `display` rule overrode `hidden`.
3. The approval dialog depended on the asynchronous `close` event, which did not fire in a background pane, so the approval was never sent. Fix: the dialog resolves from its buttons and Escape.
4. Approval and drift lists re-rendered every poll even when unchanged, so a click could miss its button. Fix: re-render only on change.

## Verification (all against the live stack)

| Check | Result | Evidence |
|---|---|---|
| Engine unit tests and historical suites | E1 13, E2 9, E3 22, E4 33, E4.1 35, E4.2 58, E4.2.1 60: all OK | `tests/runs/20261016T1840-regression-UI-P1/results.txt` |
| Live E2E, E4.2.1 | 17/17; AM11 exit 0 | `e2e/runs/20261016T182547-e2e` |
| Live E2E, default engine | 13/13; AM11 exit 0 | `e2e/runs/20261016T182817-e2e` |
| Console integration (12 journeys, auth, validation, CSRF, traversal, 503 when down, recovery and ack, reset) | 18/18 (an earlier run was 17/18, preserved) | `console/tests/runs/20261016T182229`, `console/tests/runs/20261016T183321` |
| Documented judge setup from a clean state | `demo/stop.sh` → `demo/launch.sh` → READY; then 18/18 | `submission_assets/judge_setup_test/` |
| UI walk-through in a browser | every page rendered from live data, no console errors; HR form (client and server refusal, then accepted); approval through the dialog executed exactly once at the tool server; light and dark themes | `submission_assets/screenshots/` |

## Not done or not claimed

- No hosted deployment. The demo runs locally.
- No second machine. Not SECURITY-TESTED. Not independently reviewed.
- Owner sign-off is pending (`OWNER_REVIEW_CHECKLIST_E421.md`).
- The console's demo-token injection is a local demo convenience (bound to 127.0.0.1), not an authentication design.
