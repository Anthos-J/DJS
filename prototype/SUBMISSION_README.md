# MANDATE: hackathon submission (engine E4.3, release R-E4.3; UI releases P1–P3)

**Start here:**
- `prototype/README_JUDGES.md`: quick start, architecture, troubleshooting.
- `prototype/DEMO_SCRIPT.md`: what to click and what to observe.

**First, restore the injection model** (delivered beside this ZIP as `MANDATE_E4.3_injection_model.zip`; 568 MB, verified against the frozen hash). From this folder:

```bash
python tools/restore_injection_model.py ../MANDATE_E4.3_injection_model.zip
```

Adjust the path to wherever the model archive is. See `prototype/MODEL_RESTORE.md`. Without it, E4.3 refuses to start; `MANDATE_ENGINE=E4.2.1` runs the previous engine.

**One command** (Windows 11 + Docker Desktop + Git Bash, run from `prototype/`):

```bash
bash demo/launch.sh
```

Then open http://127.0.0.1:8090. Stop with:

```bash
bash demo/stop.sh
```

## Package layout

| Path | Contents |
|---|---|
| `prototype/` | **Source**: control plane (`control/`), frozen engine (`mandate/`), configs, PEP and mock tools (`pep/`), judge console (`console/`), launcher (`demo/`), E2E driver, tests, evaluation harnesses |
| `S2-cedar/config/`, `S7-binding/{config,harness}/`, `S3-isolation/harness/`, `images/spike-py312/`, `tools/` | **Dependencies** mounted or used by the stack: Cedar policy, mTLS sidecar/terminator configs and PKI, the AM11 cell-policy gate, the image Dockerfile with its hashed dependency lock, helper tools |
| `prototype/eval/runs/…` (selected), `prototype/e2e/runs/…` (latest), `prototype/tests/runs/`, `prototype/console/tests/runs/` | **Evidence**: final evaluation summaries and outcome audits, the post-freeze red team, live E2E runs, test results. Full raw evaluation rows (`results.jsonl`, tens of MB each) are in the git repository, not in this ZIP |
| `submission_assets/screenshots/`, `submission_assets/judge_setup_test/` | **Generated demo artifacts**: screenshots of the working UI and the clean-state setup transcript |
| `prototype/RELEASE_E43.md`, `E43_TRACEABILITY.md`, `MODEL_RESTORE.md` | **Release R-E4.3**: what E4.3 adds, the detector's own tests, the live-LLM demonstration, and model storage, integrity and licences |
| `ml/behaviour_model/`, `ml/injection_detector/` | The owner's training kits (notebooks and generators) for the two learned components |
| `prototype/FINAL_STATUS_REPORT.md`, `E42_TRACEABILITY.md`, `E42_ACCEPTANCE_CRITERIA.md`, `OWNER_REVIEW_CHECKLIST_E421.md`, `UI_RELEASE_P1.md` | Evaluation summary (with the R-E4.3 section at the top), traceability, criteria, owner review (**sign-off pending**), release record |

## Status in one paragraph

**Working and verified:**
- The live prototype runs: real PEP, mTLS-bound identities, AM11-isolated cells, engine E4.3 with the injection detector loaded.
- E2E is 17/17 on E4.3 and on E4.2.1. E4.3 has 34 + 60 engine tests, and every historical suite matches its record.

**Recorded, engine-level evaluation** (AI-generated scenarios, scripted agents, mock tools; fresh seeds 961–965):
- 1,260 attack scenarios, 30 succeeded (family C4, below-budget reading: a documented limitation).
- 840 legitimate scenarios: 0 denied, 124 needed an approval.
- E4.3 and E4.2.1 are **identical** on this set. That is expected: the scenarios contain no document text, so the detector never runs, and the sequence model scores 0 points.

**Injection detector, its own held-out tests** (separate):
- 98.0% of injections caught in unseen e-mails, with 0.3% false alarms.
- 76.3% caught from a source never seen in training (CNN articles plus Lakera injections), with 0% false alarms.
- 74.6% caught on the deepset test split, with 1.8% false alarms.

These describe the detector on these datasets, not a reduction in attack success.

**Not established:**
- independent human security review;
- second-machine reproduction;
- live-LLM behaviour at scale. The controlled demonstration is 15 runs, 14 PASS: the one FAIL was a provider-side HTTP 400 on a malformed tool call from the model. It is reported separately in `prototype/RELEASE_E43.md` §4. In those runs the detector flagged every injected document, but the downstream holds in the live runs would also have happened on E4.2.1; the case where the detector decides is shown by a scripted counterfactual;
- public IPv6;
- the Antigravity audit.

This is a prototype. It is not SECURITY-TESTED, not production-ready and not vulnerability-free.

## Building the image (only if `mandate-spike-py312:wave2` is missing)

```bash
cd images/spike-py312 && docker build -t mandate-spike-py312:wave2 .
```

Internet access is needed for PyPI and the pinned Cedar/cvc5 downloads.
