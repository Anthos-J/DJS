# Owner review checklist: E4.2.1 acceptance criteria F1–F9

**Status: OWNER SIGN-OFF PENDING.** The AI prepared this checklist. Nothing here is approved until the owner fills in and dates §3. AI self-review is not independent review. Approving these criteria does not make anything SECURITY-TESTED, production-ready or vulnerability-free.

Sources: `E42_ACCEPTANCE_CRITERIA.md` (criteria, fixed before the freeze) and `FINAL_STATUS_REPORT.md` (results and evidence).

## 1. Criteria as measured by the AI (verify each yourself)

| # | Criterion | AI-measured result | Evidence to inspect | Owner check |
|---|---|---|---|---|
| F1 | E4.2.1 unit and bypass tests | 60/60 pass | `tests/runs/20261016T1900-regression-E421/results.txt` | [ ] |
| F2 | Historical suites on their own engines | E1 13, E2 9, E3 22, E4 33, E4.1 35, E4.2 58 all OK; cross-engine 19/22 and 39/44 explained | same | [ ] |
| F3 | Live path through the real PEP | E4.2.1 E2E 17/17; default 13/13; AM11 static and runtime exit 0 | `e2e/runs/20261016T172125-e2e`, `e2e/runs/20261016T172320-e2e` | [ ] |
| F4 | Fresh evaluation, reproducible | seeds 951–955, two identical decision hashes, 0 INCONCLUSIVE | `eval/runs/20261016T1800-E4.2.1-h5eval-s95x-run{1,2}` | [ ] |
| F5 | Attack outcomes | SUCCEEDED only in C4 (30 of 1,260) | same, `summary.json` → `families` | [ ] |
| F6 | Legitimate work | 0 denied, 0 quarantined; **127 of 840 needed an approval** | same | [ ] |
| F7 | Alert quality | benign alert rate 0.094 (≤ 0.15); actionable 0.0775 | same | [ ] |
| F8 | Evidence integrity | manifest 1,531 entries, 0 changed, 0 missing (at `bab2a7c`) | `python tools/verify_evidence.py verify` | [ ] |
| F9 | Every finding classified | see `FINAL_STATUS_REPORT.md` §4 | report | [ ] |

## 2. Disclosures you are accepting if you sign (tick each)

- [ ] **30 C4 attack scenarios SUCCEED.** Below-budget reading of unrelated items cannot be told apart from an authorized task with the same observable behaviour (L1/X1). No data-minimisation control was implemented.
- [ ] **127 legitimate scenarios need an owner approval:**
  - 60 are web-research wiki writes held under the R5 policy;
  - 30 are owner recovery mode;
  - 37 are routine and cold-start work, which was already slowed before this cycle.
- [ ] **No independent human security review** has been done. All red teaming is AI adversarial self-review.
- [ ] **No second-machine or clean-machine reproduction.** Everything ran on one Windows 11 + Docker Desktop host.
- [ ] **No live LLM provider test.** No key was available or used. All agents are scripted and the tools are mocks with simulated outbound effects.
- [ ] **The Antigravity audit is unavailable.** It is not in the repository and was not incorporated.
- [ ] **Public IPv6 was not validated.** Only a ULA positive control was possible; the host has no public IPv6.
- [ ] Scraping across separately authenticated owners is bounded only at 2 × the dataset quota (L2 / Z2 / V1).
- [ ] Owner-acknowledged recovery accepts lost history (V2).
- [ ] The state is not tamper-proof against someone controlling the log, checkpoint, anchor and HMAC key. Without the anchor, a rollback to an older consistent copy is undetected (V3a).
- [ ] Single process only (no multi-replica accounting). In-session taint is not persisted across a control-plane restart (L12 residual).
- [ ] The dependency lock is verified, but the image was not rebuilt from it. The Cedar/cvc5 trust-on-first-use pins are unchanged.
- [ ] The final seeds reused the h5eval name pools already used to evaluate E4.2 (L11).
- [ ] The owner UI's HR task form arrives with the submission UI release (see `SUBMISSION_README.md`). Server-side validation already existed.
- [ ] The risk score is an ordinal index of documented factors, not a calibrated probability.

## 3. Owner decision (to be completed by the owner only)

| Item | Owner entry |
|---|---|
| Decision (ACCEPT for hackathon demonstration / REJECT / ACCEPT WITH CONDITIONS) | |
| Conditions or comments | |
| Name | |
| Date | |

External-validation gates stay **OPEN** whatever is decided here: independent review, second machine, live LLM, public IPv6 and the Antigravity audit.
