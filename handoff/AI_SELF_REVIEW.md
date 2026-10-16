# Adversarial AI-assisted self-review (OA-1 condition 6)

**Reviewer:** Claude, the **same** AI system that wrote the harnesses, the engine and the prototype. **This is not an independent human review**, and shared blind spots are likely.
**Method:** re-read raw evidence (results files, tool-server effect logs, audit chains), not driver summaries, and look for false positives, false negatives, harness defects and untested assumptions.
**Date:** 16 Oct 2026.

## Findings on the new prototype work

| # | Finding | Kind | Evidence | Disposition |
|---|---|---|---|---|
| 1 | The held-out "detected" metric counts an alert **at** the harmful step. **0/300** attacks raised an alert *before* their first harmful action | Overstated metric | Rows in `eval/runs/*heldout-run2/results.jsonl` | Reported in `PRB_TRACEABILITY.md`: prevention, not early warning |
| 2 | 120/300 held-out "preventions" are approval-gated and depend on a human rejecting them | Conditional result | `attacks_only_approval_gated: 120` | Reported separately everywhere |
| 3 | `rate_spike` is inert: no rate baseline is ever recorded (`record_rates` is never called) | Untested capability | grep; factor count 0 | Kept in code, documented as inert |
| 4 | Gradual drift (`distribution_drift`) fires but never alone crosses the alert band | Weak detector | 25 firings, all inside LOW-band sums | Documented; no tuning on held-out data |
| 5 | The scenario generator was written by the same agent that wrote the engine, so it is likely to favour the engine | Evaluation bias | — | Post-freeze red team added: **2/6 evaded** |
| 6 | RT R1, R3 and R4 were stopped only because the tools were novel for those agents; with mature baselines they would probably succeed | Fragile success | `redteam_results.json` factors | Documented |
| 7 | Dev-split iterations changed engine behaviour 4 times before the freeze (approval vs accumulator, frozen reference, deviation-only accumulator, allowlist grounding, realistic instructions) | Tuning on the dev split | Commit `f7e5eb5` message | Held-out seeds and pools were untouched before the freeze |
| 8 | Cedar P is evaluated with principal `procurement` for every role. P's principal restriction is therefore meaningless in the engine; the role mandate is enforced separately | Semantic shortcut | `engine._cedar` | Documented. P is used only for its G2/G3 label rules |
| 9 | In the E2E path, trusted tool outputs are not fed back for grounding; grounding uses the task instruction only | Integration gap | `pep_proto.py` | Documented (stricter, not looser) |
| 10 | Control-plane state is in memory; a restart loses agents and approvals. The audit file persists but is not replayed | Availability gap | E9 behaviour | Documented; fails closed |
| 11 | The control plane is on `mgmtnet` (non-internal), so the container has outbound internet. The UI port is bound to 127.0.0.1 only | Exposure | `compose.yaml` | Documented residual risk |
| 12 | `toolnet` membership (PEP + backend only) is not enforced by the AM11 checker (non-cell networks are unconstrained). G0 relies on the backend being reachable only from the PEP | Unchecked assumption | `cell_policy.py` scope | Documented |
| 13 | Owner and PEP tokens are static demo values | Demo auth | `compose.yaml` | Documented; not for production |
| 14 | Harness and implementation errors during the build: an invalid JSONResponse argument; the E6b ordering; demo-mode syntax; a red-team import side effect | Harness defects | NOTE files in the runs | All fixed; runs kept |

## Spot re-checks of earlier evidence

- **S3 regression after adding the `control-plane` role:** see `STATUS.md` (rerun result recorded there).
- **E2E raw effects:** 8 tool-server effects, every one with an ALLOW decision ID; 0 HR reads; 0 emails to `collect.example`; 0 uploads.
- **Evidence integrity:** `tools/verify_evidence.py verify` and `tools/verify_manifest.py` (S3 tag: 297/297).

## What this review cannot provide

Independent judgement; a second machine; detection of blind spots shared between the builder and the reviewer.

## E2 self-review (16 Oct)

| # | Finding | Disposition |
|---|---|---|
| 15 | The E2 rules target attack *classes* known from the E1 red team; heldout2 instances are new, but the classes are not held-out | Stated in every E2 result; red team v2 written after the freeze |
| 16 | Approval-gated preventions grew from 120 to 210 on heldout2: E2 shifts reliance onto human rejection | Reported separately |
| 17 | Provenance labelling does not stop the poisoned write (A12/R5); it only taints readers | Counted as "mitigated", not "prevented" |
| 18 | Substring grounding lets short numbers match (X3) | Recorded as an evasion; fix deferred to E3 |
| 19 | The rate rule alerts but does not restrict reads (A11, 30/30 succeed) | Recorded |
| 20 | The E1 red-team harness ignores provenance labels, so it reports R5 under E2 as "evaded" | Explained in the red-team output, STATUS and traceability |
| 21 | Benign friction rose: clean completions went from 215 to 207 on heldout2 | Reported; 0 denials |
