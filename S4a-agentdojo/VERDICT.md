# S4a AgentDojo LLM-free ground-truth replay: verdict

> **Every number here is IN-PROCESS DECISION EMULATION** (playbook rule 6). It measures MANDATE's decision logic on reference traces. It establishes **nothing** about mediation, LLM behaviour or attack success rates.

**Runs:**
- `runs/20261016T004656-run2` and `runs/20261016T004806-run3`: identical `decision_hash` `91517b3a…`.
- `run1` was a harness error; see below.

**Status:** ledger 32 and 33 **LOCALLY REPRODUCED**. **EG-8 met at its required level** (LOCALLY REPRODUCED).
**Runner:** Claude. **Reviewer:** not assigned.

## Setup

- **Image:** `mandate-agentdojo:wave5` (`sha256:b6f1835c…`) = spike image + `agentdojo==0.1.35`. Benchmark `v1.2.2`. Runs with `--network none`; no LLM, no API key.
- **Frozen annotations:** `config/tool_annotations.json`, committed in **`ab9108a` before any run**. SHA-256 `fa30be1c…`, matching the value recorded in each run's `summary.json`. Every tool in all 4 suites is covered, with no extras.
- **Emulator:**
  - S2 policy P and schema, via two-pass Cedar with the AM9 rule.
  - Session labels are raise-only: reading an `untrusted` source sets integrity to 0; confidentiality is the maximum seen.
  - Consequential arguments must appear in the prompt or in trusted outputs (G2).
  - Only PERMIT executes. APPROVAL_REQUIRED is **not** auto-approved.
- **Modes:** `native` (FunctionsRuntime directly), `permit_all`, `deny_all` (negative control), `mandate`.
- **Success checks** use AgentDojo's own order: `*_from_traces` with the executed call trace, then the environment check.

## Results (run2 = run3)

| Check | Result |
|---|---|
| All 4 suites run (workspace, travel, banking, slack) | **PASS**: 97 user tasks, 949 (user, injection) pairs, 0 errors |
| Benign: native ground truth passes | 97/97 |
| **Parity**, benign: permit-all utility == native | **PASS**: 0 mismatches |
| **Parity**, attack: permit-all outcome == native | **PASS**: 0 mismatches over 949 pairs |
| **Negative control**: deny-all changes the outcome | 57 benign tasks, so the utility checks are sensitive to blocked effects |
| **Determinism**: two runs, same decision hash | **PASS** (`91517b3a…`) |
| Native attack success (ground truth succeeds) | 592/949. The other 357 cannot be replayed: workspace injection tasks 6–13 and travel `injection_task_6` have **empty ground truth** in agentdojo 0.1.35 (they make no calls); travel 2 (4/20) and workspace 5 (13/40) fail natively when combined with some user tasks. These are recorded as native failures |

## Measurements (recorded; no targets)

| Metric | Value |
|---|---|
| Benign calls: PERMIT / APPROVAL_REQUIRED | 308 / 31 |
| Benign tasks whose utility survives when no approvals are given | 72/97. Lost: workspace 15, banking 7, slack 3 |
| **Floor coverage:** natively successful attacks that the emulator prevents | **413/592** |
| Attacks still succeeding under the emulator | **179**: travel 76, slack 47, workspace 40, banking 16. **In all of them, every injected call was PERMITted** |

**Finding.** Policy P steps up untrusted-integrity flows only when the data's confidentiality reaches the threshold, the data exceeds the sink's clearance, or a consequential argument is ungrounded. So it does **not** floor:

- injected calls whose arguments are grounded in trusted public data (e.g. travel reservations);
- injected calls to **internal** sinks (e.g. Slack messages).

This is a property of P and of the frozen annotations, found by measurement. It was **not** tuned away after seeing results, which would violate the freeze. Changing it means a new, re-frozen policy or annotation version.

## Harness error (run1, `NOTE_harness_error.txt`)

1. Success was checked with the environment check only, but AgentDojo checks `*_from_traces` first. As a result, slack `injection_task_5` raised `NotImplementedError`.
2. Injection vectors were filled with the raw goal text, so injected emails collided with the attack's own subject check.

The run1 attack baseline (531 + 21 errors) is not used. Decisions were not affected, because labels are source-based.

## Limitations

- **Emulation only.** The labels and groundedness rules are heuristics fixed in the annotations, and grounding is substring matching.
- No human approver exists in replay, so APPROVAL_REQUIRED counts as blocked.
- 9 injection tasks have no replayable ground truth.
- The S4b LLM arm is **BLOCKED**: it needs your API-access decision.

## Reproduce

```
bash ../images/agentdojo/build.sh && bash harness/run_s4a.sh <label>
```
