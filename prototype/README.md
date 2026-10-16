# MANDATE prototype: identity-drift detection and enforcement for AI agents

A working prototype for the problem statement "Identity Drift Detection in Autonomous AI Agents". It contains:

- a behavioural-drift engine on top of deterministic policy;
- a control plane with a security-operations dashboard;
- real enforcement at the MANDATE PEP, inside AM11-isolated agent cells with mTLS-bound credentials.

Requirement-by-requirement status: `../PRB_TRACEABILITY.md`.

## Components

| Path | What |
|---|---|
| `mandate/engine.py` | Drift engine. Deterministic layer (credential, quarantine, role mandate, sensitivity ceiling, delegation scope, destination allowlist, frozen Cedar policy P from S2, restricted step-up), then behavioural factors, an explainable ordinal risk score, and responses (ALLOW / APPROVAL_REQUIRED / DENY / RESTRICT / QUARANTINE). Fails closed |
| `mandate/audit.py` | Hash-chained append-only audit log, with a `verify()` function |
| `config/roles.json` | Declared roles, mandates, tasks, tool catalogue (sensitivity, untrusted sources, consequential arguments) |
| `config/engine_config.json` | Factor points and thresholds (E1, frozen; SHA-256 in `eval/FROZEN_E1.sha256`) |
| `control/server.py`, `control/static/` | Control-plane API (`/api/decide` for the PEP, owner endpoints) and the dashboard |
| `pep/pep_proto.py` | PEP: S7 credential binding, then a control-plane decision per tool call. Fails closed; attaches the decision ID |
| `pep/backend_proto.py` | **Mock** tool server, including a supplier-PDF injection fixture; logs every effect (independent observer); outbound effects are **simulated** |
| `pep/agent_proto.py` | Scripted agent (**no LLM**) |
| `compose.yaml`, `run_prototype.sh` | Topology (2 AM11 cells, terminator, PEP, tool server, control) and fail-closed deploy |
| `tests/test_engine.py` | 13 unit tests (Part E categories) |
| `eval/scenarios.py`, `eval/run_eval.py`, `eval/redteam.py` | Scenario generator (dev / held-out), evaluation, post-freeze red team |
| `e2e/e2e_driver.py` | End-to-end scenarios through the real path |

## Prerequisites

- Docker Desktop (tested: 4.95.0 / Engine 29.8.2), Git Bash, host Python ≥ 3.10.
- Images: `mandate-spike-py312:wave2`, built from `../images/spike-py312`, and `nginx@sha256:56168782…`, pulled.

## Run

From `validation/prototype`.

Demo, which leaves the dashboard running:
```bash
bash run_prototype.sh demo
```
Open http://127.0.0.1:8800 and enter the token `demo-owner-token` (demo only).

Full end-to-end test, 13 checks, including the control-plane-down fail-closed test:
```bash
bash run_prototype.sh e2e
```

Unit tests, in the pinned image:
```bash
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$(cygpath -w "$(pwd)/.."):/v:ro" -w /v/prototype mandate-spike-py312:wave2 python -m unittest discover -s tests -v
```

Held-out evaluation. The expected decision hash is `31a43c07…`:
```bash
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$(cygpath -w "$(pwd)/.."):/v" -w /v/prototype mandate-spike-py312:wave2 python eval/run_eval.py /v/prototype/eval/runs/my-heldout heldout 101,102,103,104,105
```

Stop:
```bash
docker compose -f compose.yaml down -v
```

## Results (see `../PRB_TRACEABILITY.md` for detail)

| Check | Result |
|---|---|
| Unit tests | 13/13 |
| E2E | 13/13 |
| Held-out attacks | **300/300 prevented** (180 denied, **120 only approval-gated**). **0/300 alerted before the harmful step** |
| Held-out benign | 130/150 scenarios uninterrupted; 0 denials; 38/900 actions needed approval |
| Post-freeze red team | **2/6 attacks succeeded** |

The risk score is an ordinal index of documented factors, **not a probability**.
