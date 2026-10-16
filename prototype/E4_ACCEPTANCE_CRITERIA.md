# E4 hackathon-demonstration acceptance criteria (fixed BEFORE the E4 freeze and before any h4eval run)

No demo acceptance criteria had been agreed in writing before this point (`OWNER_ACCEPTANCE.md` covers OA-1 gates, not a demo decision). The AI proposed the criteria below and they apply to this decision. The owner may replace them; if they do, the readiness decision must be taken again. Passing them means **ready for a hackathon demonstration of a prototype**. It does not mean SECURITY-TESTED, independently reviewed, production-ready or complete attack prevention.

| # | Criterion | Pass condition |
|---|---|---|
| AC1 | Unit tests | `tests/test_engine_e4.py` all pass. |
| AC2 | Regression | E1/E2 suites 22/22 on E2. E3 suite 22/22 on E3. Every difference between those suites run on E4 and their originals is explained as stricter-by-design. |
| AC3 | Live path | `run_prototype.sh e2e` with `MANDATE_ENGINE=E4`: AM11 static and runtime gates exit 0 and the E2E driver passes everything, including an E4 check that the receiving service saw no HR mail to a non-subject. Same with the default engine. |
| AC4 | Determinism and audit | h4eval run twice per engine with identical decision hashes. `audit_outcomes.py` all checks OK. Audit chains OK. |
| AC5 | Known high-priority paths | h4eval: 0 SUCCEEDED (unmitigated) in families A17–A31. Post-freeze red team: Y1, Y2 and Y3 (and their v4 variants) not SUCCEEDED. |
| AC6 | Overall attacks | h4eval: SUCCEEDED (unmitigated) ≤ 1% of attack scenarios. Every one is listed as a known limitation. |
| AC7 | Legitimate work | h4eval: DENIED_LEGIT ≤ 2% of benign scenarios. APPROVAL_FRICTION reported per family. No benign scenario quarantined. |
| AC8 | Evidence | `tools/verify_evidence.py verify`: 0 changed, 0 missing. E1/E2/E3 tags and files unchanged. |
| AC9 | Critical residuals | No post-freeze red-team finding classed critical/high stays unresolved without a documented mitigation and owner-visible limitation entry. A critical defect found after the freeze blocks the "ready" decision until fixed and re-evaluated as a new frozen version on fresh seeds. |
