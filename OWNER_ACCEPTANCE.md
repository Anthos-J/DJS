# Owner acceptance: MANDATE prototype (OA-1 condition 7)

**State: NOT YET ACCEPTED.** Fill in and date this to move gates to OWNER-ACCEPTED (PROTOTYPE). Accepting does **not** make anything SECURITY-TESTED, and it is not an independent review.

## 1. Reproduce (on your machine)

- [ ] `bash prototype/run_prototype.sh e2e` → `SUMMARY 13 / 13`; unit tests 22/22, with the AM11 gate showing `static_check_exit=0` / `runtime_check_exit=0`
- [ ] `bash prototype/run_prototype.sh demo`, then open http://127.0.0.1:8800 (token `demo-owner-token`). Check: Agents, Timeline, Alerts (explained scores), Approvals (approve once), quarantine/restrict/resume, Delegation, Baselines & drift, Evaluation, Audit (chain intact)
- [ ] Unit tests: see `prototype/README.md` → 22/22
- [ ] Held-out evaluation (E2, heldout2): see `prototype/README.md` → decision hash `8ebd0968…` (E1 on held-out set 1: `31a43c07…`, tag `engine-E1`)
- [ ] `python tools/verify_evidence.py verify` → 0 changed / 0 missing

## 2. Read the honest results

`PRB_TRACEABILITY.md`, `handoff/AI_SELF_REVIEW.md`, `STATUS.md` (OA-1 section).

## 3. Residual risks you are accepting for prototype development (tick each)

- [ ] **Engine E2:** heldout2 A11 (rate burst of reads, 30/30) succeeds. Red team v2: X1 sub-ceiling scraping, X3 substring-grounded duplicate purchases and X5 in-mandate HR misuse succeed. R5 summary poisoning is only labelled; R6 executes 1 restart.
- [ ] 210/480 heldout2 preventions depend on a human **rejecting** an approval request.
- [ ] Early warning exists for 63/480 heldout2 attacks only.
- [ ] The rate rule uses declared ceilings and alerts without restricting reads; baselines are simulated; the risk score is ordinal, not calibrated.
- [ ] Benign friction: 33/240 heldout2 benign scenarios needed ≥1 approval (5.4% of actions); 0 denials.
- [ ] Agents are scripted (no LLM); the tool server and outbound effects are mocks.
- [ ] Control-plane state is in memory; demo tokens; the control plane has outbound internet on `mgmtnet`.
- [ ] Delegation is created by the owner API, not agent-to-agent; procurement cannot delegate web search (strict attenuation).
- [ ] Security spikes are LOCALLY REPRODUCED only, on one machine. There is no IPv6 bypass test; S5 egress byte accounting counts TLS-record bytes, and cut connections linger about 20 s; drift infrastructure checks are on-demand; transitive dependencies are not hash-pinned; cvc5 is pinned trust-on-first-use; `_meta` stripping needs telemetry off (AM12 not adopted); sidecar compromise is an accepted residual risk; S6 uses a mock provider only.
- [ ] The AI self-review was done by the same AI that built the system.

## 4. Decision

| Gate | Accept as OWNER-ACCEPTED (PROTOTYPE)? |
|---|---|
| EG-2 Confinement | ☐ yes ☐ no |
| EG-3 PEP interception | ☐ yes ☐ no |
| EG-4 Credential binding | ☐ yes ☐ no |
| EG-6 Egress | ☐ yes ☐ no |
| EG-7 Model route | ☐ yes ☐ no |

Owner name: ____________  Date: ____________  Signature / commit hash recorded: ____________
