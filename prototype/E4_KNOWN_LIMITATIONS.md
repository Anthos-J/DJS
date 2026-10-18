# Known-limitations register (engine E4.1; kept as history)

> **Current register:** the console's *Known limits* page (`console/static/limitations.json`) and `FINAL_STATUS_REPORT.md` §4. The E4.3 additions D1–D6 are in `RELEASE_E43.md` §6. Several items below were later fixed (L3, L4, L5, L6, L12); see the status report.

Severity is the AI's own assessment for a hackathon prototype. No limitation has been independently reviewed.

| ID | Limitation | Evidence | Impact | Severity | Mitigation / next step |
|---|---|---|---|---|---|
| L1 | Reads below every declared budget are accepted. X1 (40 reads at 19/min) executes. Budgets are declared per role and task, not learned. | red team X1 (E2–E4.1) | Up to 40 objects per 10 min, 60 distinct per day per principal and dataset can be read by a compromised agent | Medium | Tighter per-task budgets, data-minimising tool APIs, owner review of budgets |
| L2 | Pools are per root principal. Agents of different owners do not share budgets (Z2). | red team v4 Z2 (80/80 executed) | An attacker controlling several authenticated owners multiplies the budget | Medium | Dataset-level global budget; owner identity proofing (out of scope) |
| L3 | Cumulative counters are rebuilt from the audit log. If the log is deleted, counters reset (Z3). A tampered chain refuses start. | Z3 (SUCCEEDED), Z3b (prevented), `test_broken_audit_chain_refuses_start` | An operator or host compromise can reset budgets | Medium | Append-only or remote audit store; alarm on a missing log |
| L4 | Summary poisoning (R5) executes, labelled untrusted and alerted | h4eval A12 = EXECUTED_LABELLED (30); addendum v1 | Harm depends on consumers ignoring the label | Medium | Optional approval for trusted-store writes under taint (costs benign completions) |
| L5 | The first restart after poisoned logs executes (R6, 1 of 5). It is identical to the legitimate single restart. | red team R6 | One availability event | Low | Independent health signal before restart |
| L6 | Alert noise: about 0.84 alerts per benign action on h4eval | `summary.json` `benign_alert_rate_per_action` | Owner fatigue; alerts are not a precise detector | Medium | Alert aggregation and severity thresholds |
| L7 | Approval friction on routine and cold-start work: 34 of 540 benign scenarios (B1, B3), 72 benign approvals | `eval/runs/20261016T1800-E4.1-h4eval-s7xx-run1` | Owner must approve some legitimate actions | Low | Pre-existing since E2; baseline maturity |
| L8 | HR work needs an owner-declared structured scope. Undeclared HR tasks are denied (E3 allowed instruction names). | `test_E4_instruction_names_never_authorize_hr_objects` | Workload moves to the owner. Fail-closed | Low | UI field for subjects (API supports it) |
| L9 | Scripted agents (no LLM), mock tool server, simulated outbound effects. Scenarios, engine and red team were all written by the same AI. | all runs | Results measure engine logic, not real-world attack rates | High (claims) | Independent red team; real-LLM agents |
| L10 | E4 and E4.1 decide identically on h4eval. The set does not exercise Z4 aliasing; Z4 is covered only by the unit test and the red team. | identical decision hashes, runs 1800-* | The eval set is weaker than the red team for this path | Low | Add an aliasing family to a future set |
| L11 | The fresh E4.1 evaluation used new seeds (701–705) on the h4eval name pools already used for E4 | `scenarios_heldout4.py` | Held out by seed only | Low | New pools in any future set |
| L12 | Only read counters and spend are rehydrated after a restart. Pending approvals, agent status and baselines are in memory (the demo re-seeds). | E2E E9; server `seed` | A restart clears quarantine state | Medium | Persist agent status and approvals |
| L13 | Concurrency is tested in-process (one lock), not across processes or replicas | `test_concurrent_reads_counted_exactly` | Multi-replica deployments would need a shared counter store | Low | Single control-plane instance in the demo |
| L14 | Earlier OA-1 residuals still apply: one machine, LOCALLY REPRODUCED only, no IPv6 bypass test, S6 mock provider only, transitive dependencies not hash-pinned (see `OWNER_ACCEPTANCE.md` §3) | `STATUS.md` | Not SECURITY-TESTED | High (claims) | Independent validation |
