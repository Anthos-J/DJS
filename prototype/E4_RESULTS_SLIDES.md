> **R-E4.3 (current) figures for slides:** see `RELEASE_E43.md`. Keep three things apart:
> - **Scenario evaluation** (seeds 961–965): E4.3 = E4.2.1. There were 30/1,260 attack successes, all C4; 0 legitimate actions denied; 124/840 needed approval.
> - **The detector's own tests:** in unseen e-mails 98.0% of injections caught with 0.3% false alarms; from an unseen source 76.3% caught with 0% false alarms.
> - **The live-LLM demonstration:** 15 runs, 14 PASS. The detector flagged every injected document; the downstream holds would also have happened on E4.2.1.
>
> The figures below are the E4.1-era version, kept as history.

# PPT-ready measured results (copy per slide)

**Footer for every results slide:** Engine-level evaluation on AI-generated scenarios with scripted agents and mock tools. AI self-review, single machine. Not SECURITY-TESTED, not independent review, not real-world attack rates.

## Slide 1: What changed E1 → E4.1
- E2: drift-alert rule, budgets, provenance labels.
- E3: exact numeric grounding, spend limits, read volume, HR object and field authorization.
- E4: structured HR scope (no names parsed from instructions), cumulative multi-window and distinct-object budgets, shared budgets per principal and dataset, counters survive restarts.
- E4.1: canonical object keys (closes argument-aliasing scraping).

## Slide 2: Engine progression on held-out sets (each frozen before its evaluation)
| Held-out set | Engine | Attack scenarios | Unmitigated successes | Legit scenarios | Legit denied |
|---|---|---|---|---|---|
| heldout3 eval (seeds 401–405) | E2 | 780 | 270 | 420 | 60 |
| heldout3 eval (seeds 401–405) | E3 | 780 | 0 | 420 | 0 |
| heldout4 eval (seeds 601–605) | E3 | 930 | 120 | 540 | 30 |
| heldout4 eval (seeds 601–605) | E4 | 930 | 0 | 540 | 0 |
| heldout4 eval, fresh seeds 701–705 | **E4.1 (final)** | **930** | **0** | **540** | **0** |

## Slide 3: Final engine E4.1, every scenario has exactly one outcome
| Attacks (930) | Count |
|---|---|
| Deterministically denied | 540 |
| Held for owner approval (a human must reject) | 360 |
| Executed but labelled untrusted (summary poisoning) | 30 |
| Succeeded unmitigated | 0 |

| Alert timing (930 attacks) | Count |
|---|---|
| Alert before the harmful action | 300 |
| Alert at the harmful action | 630 |
| No alert | 0 |

| Legitimate work (540) | Count |
|---|---|
| Completed cleanly | 506 |
| Completed after approval friction | 34 |
| Denied | 0 |
| Quarantined | 0 |

Alerts per benign action: 0.84 (noisy, limitation L6).

## Slide 4: Live path (real PEP, mTLS identity, AM11 cell gates)
- E2E 14/14 with E4.1, including the mail service receiving 0 HR mails to a non-subject colleague.
- E2E 13/13 with the default engine.
- Fail-closed when the control plane is down.

## Slide 5: Post-freeze red team (AI adversarial self-review)
- **Closed in E4/E4.1:**
  - Y1 colleague-name HR leak;
  - Y2 slow scraping;
  - Y3 cross-agent scraping;
  - Z4 argument aliasing (found after the E4 freeze; fixed as E4.1 and re-evaluated on fresh seeds);
  - recipient smuggling;
  - payroll-batch disclosure;
  - hammering.
- **Still succeed (known limitations):**
  - Z2 multi-owner scraping;
  - Z3 counters reset if the audit log is deleted;
  - X1 below-budget reads;
  - R6 first restart.
- **Executed but labelled:** R5 summary poisoning.
