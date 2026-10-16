# MANDATE prototype: reproducible setup and live demo checklist (engine E4.1)

## Setup (Windows 11 + Docker Desktop, as validated; one machine)
1. Prerequisites: Docker Desktop running, Git Bash, Python 3.12 on the host (driver). Images are built locally. No cloud services, real credentials or live model provider are used.
2. Get the exact code:
   ```bash
   git checkout engine-E4.1
   ```
   Later commits hold evidence and docs only. Use the final commit listed in `STATUS.md` for those.
3. Verify evidence integrity (read-only):
   ```bash
   python tools/verify_evidence.py verify
   ```
4. Unit and regression tests (pinned container, no network):
   ```bash
   docker run --rm --network none -v "$(cygpath -w "$(pwd)"):/v" -w /v/prototype mandate-spike-py312:wave2 python -m unittest tests.test_engine_e41
   ```
5. Full live path with E4.1. This runs the AM11 static gate, starts the stack, runs the AM11 runtime gate, then the E2E through the real PEP (14 checks), and leaves the dashboard running:
   ```bash
   cd prototype && MANDATE_ENGINE=E4.1 bash run_prototype.sh e2e
   ```
   The default `MANDATE_ENGINE` is still E2, the earlier validated configuration.
6. Dashboard-only demo (keeps state, skips the fail-closed restart):
   ```bash
   cd prototype && MANDATE_ENGINE=E4.1 bash run_prototype.sh demo
   ```
   Open http://127.0.0.1:8800. The owner token is `demo-owner-token` unless `MANDATE_OWNER_TOKEN` is set. It is a demo token, not a credential.
7. Stop the stack: `docker compose -f compose.yaml down -v`. This only removes the prototype's own volumes; it does not reset Docker Desktop.

## Live demo checklist
- [ ] `verify_evidence.py verify` shows 0 changed and 0 missing.
- [ ] `docker inspect mandate-control-1` shows `MANDATE_ENGINE=E4.1`.
- [ ] Console shows `static_check_exit=0` and `runtime_check_exit=0` (AM11 gates).
- [ ] Normal in-role work executes (E1).
- [ ] Problem-statement example: an injected supplier PDF leads to an HR read DENIED with a valid credential, exfil DENIED, the agent QUARANTINED, and the tool server saw neither (E2).
- [ ] Alert explanation: score, factors with evidence, expected authority (E2b).
- [ ] Owner resume with a reason (E3). One-time approval: executes exactly once (E4a/b).
- [ ] Delegation chain shown; escalation denied and the child quarantined (E5/E5b).
- [ ] Cold-start label (E6a). A legitimate task change is not drift (E6b).
- [ ] E4 HR fix: a colleague named in the instruction gets **no mail at the mail service**; the colleague's record read is DENIED (E10).
- [ ] Fail-closed: control plane stopped means DENY, nothing executed (E9).
- [ ] Evaluation tab: show the measured table (`E4_RESULTS_SLIDES.md`) and say plainly it is engine-level on generated scenarios.
- [ ] State the limitations (`E4_KNOWN_LIMITATIONS.md`, at least L1–L3, L6 and L9). Do not claim complete prevention or SECURITY-TESTED.
