# OA-1: Owner-authorized validation workflow for prototype development

**Authorized by:** the project owner (instruction of 16 Oct 2026). **Recorded by:** Claude (engineering agent). **Applies from:** the commit that adds this file.
**Nature:** an explicit change to the project's *internal* gate policy. It does **not** rewrite earlier results, and it does **not** state or imply that an independent human review, an external certification or a SECURITY-TESTED verdict (playbook §3.1) has taken place.

## What changes

The playbook's **rule 7** ("two-person verdicts for SECURITY-TESTED claims") and the entry-gate requirement of SECURITY-TESTED for EG-2/3/4/6/7 **remain the standard for a security claim**. They **no longer block the owner-authorized prototype-development workflow.**

For prototype development, a gate may instead be closed at **OWNER-ACCEPTED (PROTOTYPE)** when all seven conditions below hold, with evidence:

| # | Condition | How it is evidenced in this repo |
|---|---|---|
| 1 | Reproducible tests in the available environment | Scripted runs (`run_*.sh`, `regression.sh`, `prototype/run_*.sh`) re-executed from a clean project state (`compose down -v`, then a fresh deploy) on the owner's machine |
| 2 | Independent observation at the security boundary | Backend, mock-server and provider logs, packet captures. The enforcer's own log is never sole evidence (playbook rule 2) |
| 3 | Positive controls for every negative security test | `control` field in `results.jsonl`; a failed control yields HARNESS-ERROR, not PASS |
| 4 | Pinned or recorded environment and dependencies | Image digests or IDs, `pip freeze`, tool hashes per run; residual: transitive dependencies are not hash-pinned; cvc5 pinned trust-on-first-use |
| 5 | Automated evidence-integrity verification | `tools/verify_evidence.py` (blob-based SHA-256 manifest over all run directories) and `tools/verify_manifest.py` (S3 tag manifest) |
| 6 | Adversarial **AI-assisted self-review** of raw evidence | `handoff/AI_SELF_REVIEW.md`: Claude re-examines raw evidence for false positives, false negatives, harness defects and untested assumptions. **This is not an independent human review.** The reviewer is the same AI system that built the harnesses, so shared blind spots are likely |
| 7 | Explicit owner acceptance of documented residual risks | `OWNER_ACCEPTANCE.md`, signed or dated by the owner. **Pending until the owner fills it in** |

## Status vocabulary (used from now on; earlier statuses are kept as recorded)

| Status | Meaning |
|---|---|
| LOCALLY REPRODUCED | Playbook §3.1: a minimal test shows the capability in isolation, with pinned versions and raw output |
| INTEGRATION-VERIFIED | Playbook §3.1: components work together across the boundary, observed on the receiving side |
| AUTOMATED SELF-VALIDATED | Conditions 1–6 are met: reproducible rerun in the available environment, independent observers, positive controls, recorded versions, evidence integrity verified, and AI self-review completed with its findings addressed or recorded. **Not independent; not SECURITY-TESTED** |
| OWNER-ACCEPTED (PROTOTYPE) | AUTOMATED SELF-VALIDATED **plus** condition 7 (the owner accepted the listed residual risks). Valid for internal prototype development only |
| SECURITY VALIDATION INCOMPLETE | Shown alongside the statuses above for any claim that has not reached SECURITY-TESTED (second machine + independent human review). **This applies to every security claim in this repo** |
| SECURITY-TESTED | Unchanged playbook meaning. **No claim holds this status** |

## Gate interpretation under OA-1

An entry gate that required SECURITY-TESTED (EG-2/3/4/6/7) may be marked **OWNER-ACCEPTED (PROTOTYPE)**. The full-stack *prototype* build may then proceed. The gate's security status stays **SECURITY VALIDATION INCOMPLETE** until a second-machine rerun and an independent human review happen (see `CLEAN_MACHINE_CHECKLIST.md`, which remains valid for that purpose).

## What OA-1 does not do

- It does not change any earlier result, verdict, failed-run note or finding.
- It does not convert LOCALLY REPRODUCED into SECURITY-TESTED.
- It does not remove AM11, the fail-closed deploy gate or any regression control.
- It does not authorize live-provider tests, real credentials or cloud spend. Those still need explicit owner authorization.
