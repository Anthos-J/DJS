# Owner acceptance: MANDATE prototype (OA-1 condition 7)

**State: NOT YET ACCEPTED.** Fill in and date this to move gates to OWNER-ACCEPTED (PROTOTYPE). Accepting does **not** make anything SECURITY-TESTED, and it is not an independent review.

## 1. Reproduce (on your machine)

- [ ] `bash prototype/run_prototype.sh e2e` → `SUMMARY 13 / 13`, with the AM11 gate showing `static_check_exit=0` / `runtime_check_exit=0`
- [ ] `bash prototype/run_prototype.sh demo`, then open http://127.0.0.1:8800 (token `demo-owner-token`). Check: Agents, Timeline, Alerts (explained scores), Approvals (approve once), quarantine/restrict/resume, Delegation, Baselines & drift, Evaluation, Audit (chain intact)
- [ ] Unit tests: see `prototype/README.md` → 13/13
- [ ] Held-out evaluation: see `prototype/README.md` → decision hash `31a43c07…`
- [ ] `python tools/verify_evidence.py verify` → 0 changed / 0 missing

## 2. Read the honest results

`PRB_TRACEABILITY.md`, `handoff/AI_SELF_REVIEW.md`, `STATUS.md` (OA-1 section).

## 3. Residual risks you are accepting for prototype development (tick each)

- [ ] **Two of six post-freeze adaptive attacks succeed:** wiki poisoning after a web read, and repeated in-task service restarts. Three more were stopped only by novelty.
- [ ] 120/300 held-out attack preventions depend on a human **rejecting** an approval request.
- [ ] There is no early warning before the first harmful action; gradual drift is caught only at the consequential step.
- [ ] `rate_spike` is inert; baselines are simulated; the risk score is ordinal, not calibrated.
- [ ] Benign friction: 20/150 held-out benign scenarios needed ≥1 approval (4.2% of actions).
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
