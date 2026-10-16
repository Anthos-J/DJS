# Hackathon demonstration readiness decision (engine E4.1)

Criteria: `E4_ACCEPTANCE_CRITERIA.md`, fixed before the E4 freeze. The AI proposed them; they are not yet owner-signed.

| # | Result | Evidence |
|---|---|---|
| AC1 | PASS: E4 33/33, E4.1 35/35 | `tests/runs/20261016T1900-regression/results.txt` |
| AC2 | PASS: E1/E2/E3 suites OK on their own engines. Suites vs E4: 39/44, all 5 differences stricter by design (R1, R3, R4; two E3 HR tests that relied on instruction-name subjects) | same |
| AC3 | PASS: E4.1 E2E 14/14 including E10 (0 mails to the non-subject at the mail service); default E2 E2E 13/13; AM11 static and runtime exit 0 in both. The run used E4.1, the final version, not E4. | `e2e/runs/20261016T154555-e2e`, `e2e/runs/20261016T154658-e2e` |
| AC4 | PASS: identical decision hashes on repeated runs; outcome audit all OK; audit chains OK | `eval/runs/20261016T1700-*`, `eval/runs/20261016T1800-*` |
| AC5 | PASS: 0 SUCCEEDED in A17–A31 on h4eval (E4: seeds 601–605; E4.1: seeds 701–705); red team Y1, Y2, Y3 prevented | `eval/runs/20261016T1830-E41-redteam4` |
| AC6 | PASS: 0 of 930 unmitigated successes on the generated set | outcome_audit.json |
| AC7 | PASS: 0 of 540 legitimate scenarios denied; 34 approval friction (B1/B3); 0 quarantined | same |
| AC8 | PASS: checked at the final commit (see `STATUS.md`) | `tools/verify_evidence.py verify` |
| AC9 | PASS with documented residuals. Z4 (high) was found after the E4 freeze and fixed in E4.1, then re-evaluated on fresh seeds. Z2, Z3, X1, R5 and R6 remain and are listed as L1–L5 | `E4_KNOWN_LIMITATIONS.md` |

**Decision: READY FOR HACKATHON DEMONSTRATION (prototype), using `MANDATE_ENGINE=E4.1`.**

This is not SECURITY-TESTED, not independently reviewed, not production-ready, and not complete attack prevention. Successful attack paths remain (L1–L3, L5) and are disclosed.

**The prototype is frozen from this point.** No E5 or redesign will be started. Changes are allowed only for a critical defect. Such a fix would be a new frozen version, re-evaluated on fresh seeds and recorded separately.
