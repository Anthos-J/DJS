# E3 traceability: requirement → code → test → evidence

E1 (`engine-E1`) and E2 (`engine-E2`) are unchanged. E3 is a separate candidate: `mandate/engine_e3.py` with `config/engine_config_e3.json` and `config/roles_e3.json`. It was frozen at tag `engine-E3` (`FROZEN_E3.sha256`) before any h3eval run. Dev-seed tuning is in `E3_DEV_TUNING_LOG.md`. **This is AI self-validation, not independent review. Nothing here is SECURITY-TESTED or certified.**

| Req | E3 code (engine_e3.py / config) | Tests | Evidence |
|---|---|---|---|
| P1: rolling-window read volume, all read tools counted together | `read_volume`, `reads` / `read_attempts` deques, `read_volume_windows_s` [600, 3600], `roles_e3.read_budget` | `test_fast_scraping_*`, `test_slow_scraping_*`, `test_distributed_reads_*` | h3eval A17–A20; redteam3 X1, Y2, Y3 |
| P1: unique sensitive resources | `sensitive_breadth` (`sensitive_unique`) | unit (via HR tests) | h3eval A24 |
| P1: task scope and authority; declared batches | `task_meta.read_budget` (`catalog_refresh`, `payroll_batch`); `rate_spike` skipped for declared batches | `test_legitimate_declared_batch_completes`, `test_bulk_export_only_with_declared_bulk_purpose` | h3eval B9, B11, B13 |
| P1: limits, approval and recovery; evasion | approval above budget, DENY + restrict above 2× attempts, `read_budget_extension`, counters survive task change | `test_read_budget_extension_by_approval`, `test_task_change_does_not_reset_read_counters` | h3eval A20 (window gaming) |
| P2: typed exact numeric grounding | `ground_value`, `MONEY_RE` / `NUM_RE`, `Decimal`, `ambiguous_amount` | `TestGrounding` (6 tests) | h3eval A21, B12; redteam3 X3, Y5 |
| P2: cumulative spend, duplicates, arguments changed after approval | `spend_limit` per (agent, task_epoch); approval bound to an argument hash | `test_spend_limit_and_duplicates`, `test_changed_args_after_approval_*` | h3eval A14, A22; redteam3 R1, Y4 |
| P3: object, field and purpose authorization | `object_authorization`, `field_authorization`, `task_meta.fields`, subjects/requester (declared or instruction-token) | `test_hr_object_and_field_authorization`, `test_hr_subject_grounded_*` | h3eval A23–A25, B10, B14; redteam3 Y6, Y7 |
| P3: cross-employee copy, recipient check, follow-on actions | `after_authz_violation`, `recipient_not_subject`, `tainted_sensitive_flow` exempt only for a reply to the subject | `test_hr_cross_employee_copy_*`, `test_hr_recipient_must_be_subject`, `test_consequential_action_after_authz_violation_*`, `test_leave_reply_*` | h3eval A15, A26; redteam3 X5, Y1 |
| P4: one final outcome per scenario; arithmetic audit | `eval/audit_outcomes.py`, `eval/run_eval_v3.py` | audit checks (all OK) | `eval/runs/20261016T123307-E2-heldout2-run2/outcome_audit.json`, `eval/runs/20261016T1500-{E2,E3}-h3eval-run{1,2}/` |
| P4: provenance alerting | `provenance_alert` on labelled writes | `test_provenance_write_raises_alert` | h3eval A12 (labelled, alert AT) |
| P5: regression | — | `tests/test_engine.py` + `tests/test_engine_e2.py` (22/22 on E2); `tests/run_suites_against_e3.py` (19/22; R1, R3, R4 stricter by design) | E2E with E3 `e2e/runs/20261016T125949-e2e`; E2E with E2 (default) `e2e/runs/20261016T130051-e2e`; both 13/13 with the AM11 static and runtime gates at exit 0 |

The live server selects the engine with `MANDATE_ENGINE` (default `E2`; `E3` is opt-in) in `control/server.py` and `compose.yaml`.
