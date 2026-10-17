# UI release P2: three new owner features on frozen engine E4.2.1

The engine is unchanged: `mandate/engine_e421.py`, `state_e42.py`, `audit.py`, the configs and the Cedar policy still match `FROZEN_E421.sha256`. Freeze of this release: `FROZEN_UI_P2.sha256`.

| Feature | What it does | Where | Verified by |
|---|---|---|---|
| **Policy what-if simulator** | The live engine decides any proposed tool call on a throwaway copy of the current state. Nothing goes to the PEP or the tool server, nothing is written to the audit, and no approval or quarantine is created. | `POST /api/simulate` (`control/server.py`, `sandbox()`); console page *Policy simulator* | `T07.test_simulator_is_a_true_dry_run`: decision count, approvals, quarantines and audit length identical before and after; 400 on a bad body; 401 without the owner token |
| **Attack-path graph** | A live agent → tool → destination map from real decisions. Edge thickness is call count; colour is the worst outcome (allowed, held, denied). Shows delegations and quarantined agents; clicking an edge opens Investigations. | console page *Attack graph* (client-side, from `/api/events` and `/api/delegations`) | `T07.test_ui_pages_served`; visual check (`submission_assets/screenshots/graph.png`) |
| **Verifiable incident evidence pack** | One click exports a decision with its alert, approvals, tool-server effects and the hash-chained audit records up to it. `console/verify_evidence_pack.py` (standard library only) recomputes the chain offline. | `GET /console/evidence/<decision_id>`; *Export verifiable evidence pack* button in Investigations | `T07.test_evidence_pack_verifies_and_detects_tampering`. Manual tamper tests: an edited decision fails; an edited audit record fails even with a recomputed pack digest |

Limits:
- Packs are **not signed**. They prove internal consistency up to the exported head, not authorship.
- The simulator reflects the engine's decision only. It cannot predict what an LLM agent would choose to do.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Console integration (now 21 tests) | 21/21 | `console/tests/runs/20261017T225310` |
| Live E2E, E4.2.1 | 17/17; AM11 exit 0 | `e2e/runs/20261017T225436-e2e` |
| Live E2E, default engine | 13/13; AM11 exit 0 | `e2e/runs/20261017T225541-e2e` |
