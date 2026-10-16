# Problem-statement traceability

**Source of truth:** `../DJ PRB STATEMENT.pdf` ("Identity Drift Detection in Autonomous AI Agents").
**Status values:**
- **IMPLEMENTED:** implemented and demonstrated by a reproducible test or evaluation;
- **PARTIAL:** implemented with a documented gap;
- **MISSING**, **FAIL** or **BLOCKED**.

Security statuses follow `WORKFLOW_AMENDMENT_OA1.md`. **Every row is also SECURITY VALIDATION INCOMPLETE** (no second-machine rerun, no independent human review).

**Evidence keys** (paths under `validation/prototype/` unless noted):

| Key | Content |
|---|---|
| UT | `tests/test_engine.py`: 13 unit tests, 13 pass |
| HO | Held-out evaluation `eval/runs/20261016T112618-heldout-run2/`: seeds 101–105, disjoint name pools; engine E1 frozen in commit `f7e5eb5`. Deterministic, matching run1's hash `31a43c07…` |
| RT | Post-freeze adaptive red team: `eval/runs/*-redteam-E1/` |
| E2E | Real PEP path, `e2e/runs/20261016T113333-e2e/`: 13/13 |
| SEC | Earlier spikes S1–S8 (`../STATUS.md`) |

## Functional requirements

| # | Requirement (from the PDF) | Implementation | Acceptance criterion | Test / evaluation | Current evidence | Status | Outstanding work |
|---|---|---|---|---|---|---|---|
| R1 | "learns the normal behavior of AI agents" | `mandate/engine.py`: `learn()` builds role and per-agent tool/destination frequency baselines, plus a **frozen reference** distribution for drift. Online updates come only from clean (low-risk, non-anomalous) actions | Baselines are built from benign history; novel and rare actions are scored against them; drift is measured against the frozen reference | UT 01, 05, 08; HO B1/B3; dashboard *Baselines & drift* | UT pass; HO benign 130/150 complete. The baseline is visible per agent | **PARTIAL** | The demo baseline is **simulated benign history** (labelled). There is no learning from real deployments. The action-rate baseline exists in code but is never populated, so `rate_spike` is **inert**. There are no time-of-day or argument-level features |
| R2 | "continuously compares it with each agent's declared role" | Every tool call through the PEP calls `/api/decide`: role mandate, task scope, sensitivity ceiling, destination allowlist, policy P, behavioural factors | Each mediated action is compared against the declared role and the active task, and the comparison is recorded | UT 02, 04, 06; E2E E1–E6; HO all families | Every PEP call has a control decision (E2E E7: 8/8 effects correlated) | **IMPLEMENTED** (for mediated traffic) | "Continuous" means *per action at the PEP*. The infrastructure drift check (AM11) is deploy-time or on-demand |
| R3 | "detects when ... behavior no longer matches that role, even though its credentials are still valid" | The deterministic out-of-role, sensitivity, delegation and destination checks run **after** credential binding succeeds (S7 identity). Behavioural factors flag in-role drift | A valid-credential out-of-role action is detected and stopped | UT 02; HO A1 (30/30 blocked); E2E E2 (PDF example: HR read denied with a valid mTLS-bound credential; agent quarantined) | E2E E2 PASS; the tool server saw **0** HR reads | **IMPLEMENTED** | In-role misuse is covered only partly; see C6, C11 and RT R5/R6 |
| R4 | "explain every alert with a clear risk score" | Every decision and alert carries `risk_score` (ordinal 0–100), `risk_band`, factor list with points and evidence text, expected authority, reason, response, and confidence label; all hash-chain audited | Score = sum of the documented factor points; every factor has evidence; deterministic | UT 10; E2E E2b; dashboard *Alerts* | UT 10 PASS (score equals the factor sum; identical across engines); E2E E2b PASS | **IMPLEMENTED** | The score is **not calibrated** and is not a probability (by design; no data to calibrate). Weights were set by the engineering agent and tuned in 3 dev iterations |
| R5 | "restrict or isolate the agent without disrupting legitimate work" | Responses: ALLOW / APPROVAL_REQUIRED (one-time owner grant) / DENY, plus RESTRICT (reads continue, consequential actions need approval) and QUARANTINE (all denied; delegations suspended). Owner resume needs a reason. Enforced at the PEP | Violations are stopped; legitimate work continues; recovery works | UT 11; E2E E2–E4, E9; HO benign metrics | HO: **0 benign denials** of 900 benign actions; 38 approvals (4.2%); 130/150 benign scenarios fully uninterrupted. E2E resume, one-time approval and fail-closed all PASS | **IMPLEMENTED** (with measured friction) | 20/150 benign scenarios still need ≥1 approval. Control-plane state is in memory, so a restart loses approvals and agent state (fail-closed, but disruptive) |

## Core challenges

| # | Challenge (from the PDF) | Implementation | Acceptance criterion | Test / evaluation | Current evidence | Status | Outstanding work |
|---|---|---|---|---|---|---|---|
| C6 | "Valid credentials hide the attack" | Behaviour and mandate checks independent of the credential; S7 binding ensures the identity is real | Attacks with valid credentials are stopped | HO A1–A10 (all with valid identities); E2E E2, E5 | HO **300/300 attack scenarios prevented** (180 deny, 120 approval-gated); RT **2/6 evaded** | **PARTIAL** | RT R5 (wiki poisoning after a web read) and R6 (repeated in-task service restarts) **succeed**. 120 HO preventions **depend on a human rejecting the approval request** |
| C7 | "Indirect prompt injection ... documents, web content, messages" | Source-based taint: reading an `untrusted` tool output (supplier doc, inbox, web, logs) sets session integrity 0; then `untrusted_influence`, P's G3b and grounding apply to consequential actions | An injection-induced exfiltration is blocked or gated | UT 03; HO A2 (30/30 blocked), A3 (30/30 approval-gated); E2E E2 | PASS as stated | **PARTIAL** | No content inspection: the engine does not read the injected text. Content-level harm inside allowed actions is not caught (RT R5). Messages from other agents are covered only through delegation scope, not through taint across agents |
| C8 | "Legitimate change vs. adversarial drift ... without over-triggering" | Owner-declared `assign_task` / `change_role` move the active scope (not drift); undeclared scope deviation scores `task_scope_deviation` | Declared changes complete; undeclared ones are flagged; the false-positive rate is measured | UT 06; HO B2 (30/30 complete), B5 (30/30 complete); E2E E6b | HO benign false-positive alert rate **0.042 per action**; 0 denials | **IMPLEMENTED** (measured) | Undeclared but legitimate change is indistinguishable from drift by design; it costs approvals |
| C9 | "Little or no history" | Cold start: role prior used and decisions labelled "low (cold start: role prior)"; deterministic policy needs no history | New agents keep working; cold-start attacks are stopped; the label is shown | UT 05; HO B3 (21/30 complete, 14 approvals, 0 denials), A9 (30/30 blocked); E2E E6a | PASS as stated | **IMPLEMENTED** (measured friction) | Cold-start benign friction is higher (9/30 scenarios need approval) |
| C10 | "Chains of agents ... responsibility and authority" | `delegate()` requires child scopes ⊆ child role ∩ (parent capabilities, or child reads). Every delegated decision records the chain and root owner. Quarantining a parent suspends its delegations | Escalation is denied; the chain is visible; a compromised parent cannot act through children | UT 07; HO A5, A10 (30/30 each), B4 (30/30 complete); E2E E5, E5b | PASS as stated; the chain is shown in the timeline and *Delegation* views | **PARTIAL** | Delegation is created through the owner API, not agent-to-agent through the PEP (the `delegate_task` tool exists in the catalogue but is not wired). Strict attenuation means procurement **cannot** delegate web search (owner decision). There is no cross-agent taint propagation |
| C11 | "Evasion: copy normal behavior or change it slowly" | Frozen-reference JS divergence, deviation-only drift accumulator (auto-quarantine), repeated-anomaly factor, plus deterministic floors | Gradual and mimicry attacks are stopped; early warning is measured | UT 08; HO A7, A8 (30/30 each, **all by approval gate**); RT R1–R6 | Drift factor fires, **but no attack raised an alert before its harmful step** (0/300). RT: 2/6 evaded; R1/R3/R4 were stopped only because the tool was *novel* for that agent | **PARTIAL** | No early warning for slow drift. Evasion resistance relies on the approval gate and on novelty. Mature baselines would weaken it. The `rate_spike` factor is inert |

## Supporting security properties (earlier spikes; unchanged)

| Property | Evidence | Status |
|---|---|---|
| Complete mediation (cell isolation, AM11) | S3 canonical + regression (rerun after the `control-plane` role was added) | LOCALLY REPRODUCED; prototype topology passes the AM11 static and runtime gate on every deploy |
| Credential confinement and binding | S7 38/38; prototype reuses the S7 sidecar, terminator and binding | LOCALLY REPRODUCED / INTEGRATION-VERIFIED (22, 25) |
| Egress / model route | S5 v2, S6 | LOCALLY REPRODUCED. **Not wired into the prototype** (the prototype has no sandbox or model route) |

## Not claimed

Calibrated risk probabilities; LLM-agent behaviour (all agents are scripted); real-world attack rates; independent review; SECURITY-TESTED status.
