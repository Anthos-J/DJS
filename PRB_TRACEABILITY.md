# Problem-statement traceability (engine E2)

> **Current engine: E4.3.** Requirement → implementation → test → evidence for E4.3: `prototype/E43_TRACEABILITY.md`; for E4.2/E4.2.1: `prototype/E42_TRACEABILITY.md`. This file is the original E2 matrix, kept as history.

**Source:** `../DJ PRB STATEMENT.pdf`. The previous (E1) version of this file is in git history at commit `f80c6c5`.

**Status values:**
- **IMPLEMENTED:** implemented and demonstrated by a reproducible test or evaluation;
- **PARTIAL:** implemented with a documented gap;
- MISSING, FAIL, BLOCKED.

**Every row is also SECURITY VALIDATION INCOMPLETE** (OA-1: no second machine, no independent human review). Agents are scripted (no LLM), and the tool server is a mock. The risk score is ordinal, **not a probability**.

**Evidence keys** (under `validation/prototype/`):

| Key | Content |
|---|---|
| UT | `tests/`: 22 unit tests (13 E1 + 9 E2), all pass |
| H2 | Held-out set 2 (`eval/scenarios_heldout2.py`, seeds 201–205, new pools). **E2:** `eval/runs/20261016T123307-E2-heldout2-run2` (identical to run1, hash `8ebd0968…`). **E1 on the same set:** `eval/runs/20261016T123315-E1-on-heldout2`. E2 was frozen in `91eaf76` / tag `engine-E2` **before** any heldout2 run |
| H1 | Held-out set 1 (E1): `eval/runs/20261016T112618-heldout-run2` |
| RT2 | Post-freeze red team against E2: `eval/runs/*-redteam-E2/` |
| E2E | Real PEP path with E2: `e2e/runs/20261016T123436-e2e` (13/13) |

## Headline numbers (H2: 480 attack scenarios, 240 benign)

| | E1 | **E2** |
|---|---|---|
| Attacks prevented | 330 | **420**: deterministic deny 210; policy-P approval gate 90; effect-budget gate 60; tainted-flow gate 30; behavioural gate 30 |
| …of which require a human to **reject** an approval | 120 | **210** |
| Executed but provenance-labelled untrusted (A12 summary poisoning) | 0 | 30 |
| **Attacks that succeeded** | 150 (A11–A15) | **30** (A11: rate burst of in-role reads) |
| Attacks with an alert **before** the first harmful action | 30 | 63 |
| Benign scenarios completed with no intervention | 215/240 | 207/240 |
| Benign actions denied | 0 | **0** |
| Benign actions needing approval | 50/1170 | 63/1170 (5.4%) |
| Benign quarantines | 0 | 0 |

**Breakdown of benign scenarios not completed cleanly** (H2 E2: 33 scenarios; H1 E1: the 20 asked about). **No benign action was denied in either set.** Every non-clean benign scenario was an approval request from a documented rule:

| Cause | Rule | Assessment |
|---|---|---|
| HR record update after reading the inbox | tainted-flow / behavioural step-up | Intended: untrusted email influencing a sensitivity-3 write |
| Research web fetch after reading internal data | policy P G3a | Intended: the URL could carry internal data (the same control that stopped red-team R2) |
| More than 1 service restart in 10 minutes (devops routine) | effect budget | Intended availability control; friction for routines that restart often |

The per-scenario list is in H2 `summary.json` → `benign_not_clean`. These are **approval friction, not false denials**. Whether they are acceptable is the owner's decision.

## Functional requirements

| # | Requirement | Implementation | Acceptance test / evaluation | Raw evidence | Status | Remaining limitation |
|---|---|---|---|---|---|---|
| R1 | Learn normal behaviour | `mandate/engine.py` `learn()`: role and agent tool/destination baselines; a **frozen reference** distribution for drift; online updates only from clean actions; **owner-approved actions never update the baseline** (audited as `approved_action_not_learned`) | UT `test_08`, E2 `test_approved_actions_do_not_poison_baseline`; H2 B-families | UT output; H2 rows | **PARTIAL** | Demo baselines are **simulated** history. Rate uses a **declared** per-role ceiling; a learned rate baseline is supported only when history has timestamps |
| R2 | Continuously compare with declared role | Every PEP tool call goes to `/api/decide`: role mandate, task scope, ceilings, destinations, policy P, behavioural factors | E2E E1–E7; UT 02/04/06 | E2E `tool_effects.jsonl` (8/8 effects correlated to ALLOW decisions) | **IMPLEMENTED** for mediated traffic | Per action at the PEP; infrastructure drift (AM11) is checked at deploy time or on demand |
| R3 | Detect drift despite valid credentials | Deterministic out-of-role, ceiling, delegation and destination checks after S7 binding; E2 drift-alert rule (deviation from the declared task **and** learned behaviour); rate counter; effect budgets; tainted-flow | UT 02, E2 drift/rate tests; H2 A1–A16; E2E E2 | E2E E2: HR read denied with a valid mTLS-bound credential, 0 HR reads at the tool server | **PARTIAL** | A11 (scraping under the ceiling) and RT2 X1/X3/X5 succeed (below) |
| R4 | Explain every alert with a clear risk score | Each decision and alert has an ordinal score, band, factors with points and evidence, expected authority, reason, confidence label, and **stopping control** (E2). All hash-chain audited | UT 10, E2 `test_control_attribution`; E2E E2b | Dashboard *Alerts*; `control_audit.jsonl` | **IMPLEMENTED** | Not calibrated. Weights were chosen by the engineering agent and tuned on the dev split only |
| R5 | Restrict or isolate without disrupting legitimate work | ALLOW / APPROVAL_REQUIRED (one-time grant) / DENY, RESTRICT, QUARANTINE (delegations suspended); owner resume with reason; fails closed at the PEP | UT 11; E2E E2–E4, E9; H2 benign | H2: 0 benign denials, 0 benign quarantines | **IMPLEMENTED** (with measured friction) | 33/240 benign scenarios need an approval; control-plane state is in memory |

## Core challenges

| # | Challenge | Implementation | Test / evaluation | Status | Remaining limitation |
|---|---|---|---|---|---|
| C6 | Valid credentials hide the attack | As R3 | H2: 420/480 prevented and 30 mitigated; RT2 | **PARTIAL** | 30 H2 successes (A11); 210 preventions need a human rejection |
| C7 | Indirect prompt injection (docs, web, messages) | Source taint; tainted-flow step-up; **provenance labels** on trusted-store writes (readers inherit taint) | UT 03, E2 R5 test; H2 A2/A3/A12/A13/A15; E2E E2 | **PARTIAL** | No content inspection. A12 still writes the poisoned summary; it is labelled, not blocked. There is no cross-agent taint over direct messages |
| C8 | Legitimate change vs drift, without false alarms | Owner-declared task/role changes reset the drift window and scope; the drift rule needs deviation from learned behaviour too | UT 06, E2 drift test; H2 B2/B5 (30/30 each) | **IMPLEMENTED** (measured) | An undeclared legitimate change costs approvals |
| C9 | Little or no history | Role prior plus deterministic policy; low-confidence label | UT 05; H2 B3 (17/30 clean, 0 denials), A9 | **IMPLEMENTED** (measured friction) | Higher approval rate for new agents |
| C10 | Chains of agents | Attenuated delegation; chain and root recorded; parent quarantine suspends children | UT 07; H2 A5, A10, B4; E2E E5/E5b | **PARTIAL** | Delegation goes through the owner API, not the agent-initiated PEP path; strict attenuation forbids delegating web search |
| C11 | Evasion (mimicry, slow change) | Frozen-reference drift, drift-alert window, accumulator, rate ceiling, effect budgets | H2 A6/A7/A8/A16 prevented, A16 with early warning on 30/30; RT2 | **PARTIAL** | **RT2 successes:** X1 scraping at 19/min; X3 duplicate purchases with substring-grounded amounts; X5 in-mandate HR record misuse without untrusted input |

## Remaining successful attacks (all recorded, none tuned away)

| Source | Attack | Why it succeeds | Minimal next step (would be E3, evaluated on new data) |
|---|---|---|---|
| H2 A11 (30/30) | Burst of in-role reads; the rate spike fires as an early warning | Reads are never restricted by the rate rule | Rate-limit or restrict after a rate alert |
| RT2 X1 | Scraping kept just under the ceiling | Under the threshold by construction | Volume budgets per task or session |
| RT2 X3 | Duplicate purchases with amounts 90 and 9 that substring-match "900" | Substring grounding; the budget counts identical arguments only | Token or number-exact grounding; per-tool count budget for purchases |
| RT2 X5 | HR assistant copies another employee's data into a record (no untrusted input) | In-mandate, untainted, content-level | Data-flow or field-level policy (outside this engine's model) |
| E1 RT R5 under E2 | Summary poisoning | Executed but labelled untrusted (mitigated, not prevented) | Optional approval for trusted-store writes under taint (costs benign B6 completions) |
| E1 RT R6 under E2 | Repeated restarts | 1 of 5 harmful restarts executes; 4 are gated | — (budget by design allows 1) |

## E4 / E4.1 addendum (16 Oct 2026). The E2 table above is kept as historical.

The full requirement → code → test → evidence map for E4 is in `prototype/E4_TRACEABILITY.md`. Limitations are in `prototype/E4_KNOWN_LIMITATIONS.md`, and the readiness decision is in `prototype/E4_READINESS_DECISION.md`.

| Earlier gap | E2 status | E3 status | E4.1 status | Evidence |
|---|---|---|---|---|
| RT2 X1: below-ceiling scraping | gap | budgets | **PARTIAL**: below-budget reads accepted by design (L1) | red team v4 |
| RT2 X3: substring amounts | gap | IMPLEMENTED (typed grounding) | IMPLEMENTED. Reclassified as DENIED in addendum v1 | `eval/REDTEAM_E3_ADDENDUM_v1.md` |
| RT2 X5 / Y1: HR copy and colleague leak | gap | PARTIAL (instruction-name subjects) | **IMPLEMENTED**: structured scope plus a recipient DENY, verified at the mail service (E2E E10) | `e2e/runs/20261016T154555-e2e` |
| Y2: slow scraping | — | gap | **IMPLEMENTED**: cumulative and distinct budgets; E4.1 canonical keys (Z4) | h4eval A28; red team Y2, Z1, Z4 |
| Y3: cross-agent scraping | — | gap | **IMPLEMENTED** within one principal; **PARTIAL** across principals (Z2, L2) | h4eval A29–A31; red team Z2 |
| R5: summary poisoning | executed-labelled | executed-labelled | **PARTIAL**: executed-labelled (L4) | h4eval A12 |
| R6: repeated restarts | 1 of 5 | 1 of 5 | **PARTIAL**: first restart executes (L5) | red team R6 |

Every row is still SECURITY VALIDATION INCOMPLETE.

## E4.2 / E4.2.1 addendum (16 Oct 2026)

The requirement → implementation → test → evidence matrix is `prototype/E42_TRACEABILITY.md`. The per-item status (FIXED AND VERIFIED / PARTIALLY MITIGATED / DOCUMENTED LIMITATION / EXTERNAL VALIDATION PENDING) is in `prototype/FINAL_STATUS_REPORT.md` §4. The E2 and E4 tables above are kept as historical. Every row is still SECURITY VALIDATION INCOMPLETE.
