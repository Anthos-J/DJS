# MANDATE: hackathon submission (engine E4.2.1, UI release P1)

**Start here:**
- `prototype/README_JUDGES.md`: quick start, architecture, troubleshooting.
- `prototype/DEMO_SCRIPT.md`: what to click and what to observe.

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
| `prototype/FINAL_STATUS_REPORT.md`, `E42_TRACEABILITY.md`, `E42_ACCEPTANCE_CRITERIA.md`, `OWNER_REVIEW_CHECKLIST_E421.md`, `UI_RELEASE_P1.md` | Evaluation summary, traceability, criteria, owner review (**sign-off pending**), release record |

## Status in one paragraph

**Working and verified:**
- The live prototype runs: real PEP, mTLS-bound identities, AM11-isolated cells, engine E4.2.1.
- 12 judge journeys pass against the running stack. E2E is 17/17; 60 engine tests and 18 console integration tests pass.

**Recorded, engine-level evaluation** (AI-generated scenarios, scripted agents, mock tools):
- 1,260 attack scenarios, 30 succeeded (family C4, below-budget reading: a documented limitation).
- 840 legitimate scenarios: 0 denied, 127 needed an approval.
- Benign alert rate 0.094.

**Not established:**
- independent human security review;
- second-machine reproduction;
- a live LLM provider;
- public IPv6;
- the Antigravity audit.

This is a prototype. It is not SECURITY-TESTED, not production-ready and not vulnerability-free.

## Building the image (only if `mandate-spike-py312:wave2` is missing)

```bash
cd images/spike-py312 && docker build -t mandate-spike-py312:wave2 .
```

Internet access is needed for PyPI and the pinned Cedar/cvc5 downloads.
