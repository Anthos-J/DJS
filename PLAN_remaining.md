# Remaining validation plan (from commit 0175cd8, 15 Oct 2026)

Source: playbook §4 (execution order), §5 (spike specs), §8 (entry gate); `STATUS.md` *Wave 2*.

## Dependency order

| Order | Spike | Depends on | Prerequisite state | Ledger / gate | Notes |
|---|---|---|---|---|---|
| 1 | **S5** HTTP egress PEP (mitmproxy 12.2.3) | S3 (bypass tests T5/T10 need the cell profile) | S3 canonical AM11 LOCALLY REPRODUCED ✔ | 26–29 → EG-6 | Fully local. New pinned image: spike image + mitmproxy 12.2.3 |
| 2 | **S6** Model route (mitmproxy reverse) | S3; shares mitmproxy know-how with S5 | ✔ (after S5's image) | 30–31 → EG-7 | Mock provider only. T9 (live key) is optional and needs a human decision on API access |
| 3 | **S4a** AgentDojo ground-truth replay (LLM-free) | S2 | S2 LOCALLY REPRODUCED ✔ | 32–33 → EG-8 | Needs `agentdojo==0.1.35`. The tool-annotation file must be frozen and hashed **before** any run. Output is labelled "in-process decision emulation" (rule 6) |
| 4 | **S8** End-to-end smoke | S1, S5, S6, S7 | Waits for S5 and S6 | 35 → EG-9 | Composes every enforcement point in one AM11 cell |
| — | S4b LLM smoke | S4a + API access decision | **Blocked on a human decision** (§10) | 34 (not a gate blocker) | — |
| — | Clean-environment rerun + independent review | all SECURITY-TESTED targets | **Requires a second machine and a human reviewer** | EG-2, EG-3, EG-4 (and 23/24/26–28/30/31) | Cannot be done by the runner on this machine |

## Conventions carried forward

- Pinned images by digest or ID.
- The AM11 static and runtime gate runs before tests; a non-compliant deployment is never tested.
- Every negative test has a positive control. A negative test with a failed control is a HARNESS-ERROR, not a PASS.
- Enforcement is judged at an independent observer (server logs or a pcap), not at the enforcer.
- Harness errors are kept with NOTE files.
- Earlier runs, the baseline-failure evidence and `S3-isolation/EVIDENCE_MANIFEST.sha256` (verifies against tag `s3-am11-local-repro`) are never modified.

## This session

Execute **S5** (first in order; prerequisites met). S6, S4a and S8 follow in later sessions, in the order above.

## Progress

- 15 Oct: S5 executed (`65d800e`).
- 16 Oct: S6 executed; S5 ledger 29 implemented and tested (v2).
- **Next dependency-ready phase: S4a.** S8 follows.
- 16 Oct: S4a executed (annotations frozen in `ab9108a`); S8 executed. S6 Content-Length defect found by S8, fixed, re-tested.
- **All spikes have been executed locally.** Outstanding: second-machine clean rerun + independent review (EG-2/3/4/6/7); T9 / S4b decisions.
