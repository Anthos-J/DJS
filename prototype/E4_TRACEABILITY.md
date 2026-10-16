# E4 / E4.1 traceability: requirement → code → test → evidence

**Versions.**
- E1 `engine-E1`, E2 `engine-E2`, E3 `engine-E3` (`e79b725`): unchanged.
- E4 `engine-E4` (`7313ac6`): frozen before h4eval.
- E4.1 `engine-E4.1` (`496924c`): fixes post-freeze red-team finding Z4. Frozen before the fresh eval seeds 701–705.
- The live server selects the engine with `MANDATE_ENGINE` (`E2` default | `E3` | `E4` | `E4.1`).

**Scope.** This is AI adversarial self-review on one machine. It is not independent human review and not SECURITY-TESTED.

| Req | Code (`mandate/engine_e4.py`; E4.1 = `engine_e41.py`) | Tests | Evidence |
|---|---|---|---|
| P1 Y1: names in instructions never authorize HR access | `is_subject()`: declared `subjects` / `requester` only, exact normalised match | `test_E4_instruction_names_never_authorize_hr_objects`, `test_Y1_*`, `test_ambiguous_and_variant_names_denied` | h4eval A27, B17; red team Y1, Y7, Z5 |
| P1: target, fields, purpose, destination, principal | `object_authorization`, `field_authorization` (task_meta purpose and fields), destination allowlist, PEP mTLS identity (S7) | E3 HR tests carried over | h4eval A23–A26 |
| P1: HR disclosure only to authorized recipients | hard DENY `recipient_authorization` when HR data is in the session and the recipient is not a subject | `test_hr_recipient_must_be_subject` (E4 version), `test_Y1_*` | red team Z5, Z6 |
| P1: final effect checked at the receiving service | E2E E10 reads the mock mail service's effect log | `e2e/e2e_driver.py` E10 | `e2e/runs/20261016T154555-e2e` (14/14, mails_to_dave=0) |
| P2 Y2: cumulative multi-window limits | `per_600s` / `per_3600s` / `per_86400s`; `distinct_per_day` / `distinct_per_week` (`roles_e4.json`) | `test_Y2_*`, `test_repeated_reads_of_same_items_are_not_scraping` | h4eval A28, B18; red team Y2, Z1 |
| P2: distinct resources, sensitivity, repeated access | distinct-object sets; `sensitive_breadth`; E4.1 canonical object key over all arguments | `test_Z4_*`, `test_whitespace_case_variants_are_the_same_object` | red team Z4 (E4: SUCCEEDED; E4.1: APPROVAL_PENDING) |
| P2: alert leads to restriction, approval or denial | step-up above budget; DENY + restrict above 2× attempts; owner read-budget extension | E3 tests carried over | red team Z7 (DENIED) |
| P2: counter resets and restarts | counters are not reset by task change; `_rehydrate()` from the verified audit chain; a broken chain refuses start | `test_restart_rehydrates_counters_and_spend`, `test_broken_audit_chain_refuses_start` | red team Z3b (prevented), Z3 (audit lost: SUCCEEDED, limitation L3); E2E E9 restart |
| P3 Y3: shared budgets across agents | `pool_reads[(root principal, dataset)]`; `_principal()` follows delegation roots | `test_Y3_*`, `test_new_agent_id_does_not_reset_pool`, `test_delegated_children_share_the_root_principal_pool` | h4eval A29–A31; red team Y3, Z7 |
| P3: legitimate multi-agent work | `task_meta.pool_agents` (`parallel_catalog_refresh`) | `test_declared_parallel_workload_sized_pool` | h4eval B15, B16 |
| P3: concurrent requests | engine `RLock` around `decide` | `test_concurrent_reads_counted_exactly` | — (in-process only, L14) |
| P4: corrected classification of X3, R5, R6, X1 | `eval/REDTEAM_E3_ADDENDUM_v1.md` (original results kept) | — | `eval/runs/20261016T1530-E3-redteam3/` |
| P4: labels, effects and outcomes agree | `eval/audit_outcomes.py` (one outcome per scenario) | all checks OK on every run | `eval/runs/20261016T1700-*`, `eval/runs/20261016T1800-*` |
| P5: freeze and dev/eval separation | `FROZEN_E4.sha256`, `FROZEN_E41.sha256`, `E4_ACCEPTANCE_CRITERIA.md` (fixed before the freeze) | — | h4dev 501–502 (dev only); h4eval 601–605 (E4); h4eval 701–705 (fresh, E4.1) |
| Regression | — | E1/E2/E3/E4/E4.1 suites all OK on their own engines. Suites vs E3 19/22, vs E4 39/44; every difference is stricter by design | `tests/runs/20261016T1900-regression/results.txt`; E2E default E2 `e2e/runs/20261016T154658-e2e` (13/13) |
