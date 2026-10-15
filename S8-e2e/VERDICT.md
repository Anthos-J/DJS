# S8 End-to-end integration smoke: verdict

**Runs:** `runs/20261016T010447-run3` and `runs/20261016T010602-run4`: **18/18 PASS** each.
- `run1`: one harness error (curl `-S` missing), with a NOTE file.
- `run2`: 17/17 PASS, but it predates the G0-checker negative control. Superseded, with a NOTE file.

**Status:** ledger 35 **INTEGRATION-VERIFIED (local; one scripted scenario)**. **Not SECURITY-TESTED.**
**Runner:** Claude. **Reviewer:** not assigned.

## Composition (`config/compose.yaml`; AM11 static and runtime gate passed before every run)

- **Cell A** (`cellnet_a`, AM11):
  - `sidecar_a`: S7 nginx; holds the cell certificate and JWT.
  - `agent_a`: hardened; runs the scripted agent, no LLM.
  - Gateways: `terminator` (S7 mTLS) → `pep` (S7 binding + S1 proxy + **S2 policy P, two-pass Cedar, AM9**) → `backend`; and `model-proxy` (S6, **with the Content-Length fix**) → `mock-provider`.
- **Cell S** (`cellnet_s`, AM11): `sandbox` behind `egress` (S5 **v2**, tunnel byte accounting) → `allowed-srv` / `denied-srv`.
- **Images:**
  - spike `sha256:44bc7e00…` (pki, backend, pep, agent_a);
  - mitm `sha256:0ac91aba…` (egress, model-proxy, sandbox, servers, provider);
  - nginx `sha256:56168782…`;
  - netshoot `sha256:b09d9b21…`.

## Scripted session and results (run3 = run4)

| ID | Step / check | Result | Evidence |
|---|---|---|---|
| C-observer-denied-srv | Direct contact with denied-srv is logged | **PASS** | positive control for the egress observer |
| STEP-list-tools | `tools/list` via sidecar → terminator → PEP | **PASS** | read_doc, read_hr, send_report |
| STEP-allowed-read | `read_doc` | **PASS** | PERMIT; executed |
| STEP-denied-read | `read_hr` | **PASS** | DENY (P `hard-hr`) |
| STEP-approval-required | `send_report` to an external sink | **PASS** | APPROVAL_REQUIRED → "pending approval", not executed (G3a: conf 2 > clearance 0) |
| STEP-unknown-tool | `drop_tables` | **PASS** | DENY (not allowlisted) |
| STEP-sandbox-allowed / denied | Sandbox fetch via egress | **PASS** | 200 / 403; CONNECT to denied-srv 403 |
| STEP-model-allowed / server-tool | Model calls via model-proxy | **PASS** | 200 / 400 (`web_search_20260209` rejected) |
| **G0-coverage** | Every effect observed at the tool server, allowed-srv, denied-srv or the provider has an **earlier allowing decision** (tool server: one decision per effect) | **PASS** | 4/4 effects covered: tool-server `read_doc` (decision → effect 33 ms in run2), allowed-srv tcp + http (egress allow), provider request (model-proxy forward, same SHA-256) |
| G0-positive-effects | Allowed actions did produce observed effects | **PASS** | observers work |
| **G0-zero-denied-effects** | read_hr / send_report / drop_tables: 0 at the tool server; denied-srv: 0 contacts from egress; provider: 0 requests with server tools | **PASS** | |
| **C-G0-detects-unmediated-effect** | Negative control: a direct backend call from inside the PEP container that skips the decision middleware | **PASS** | flagged as **1 uncovered effect**, so the G0 check is not vacuous |
| G0-identity-binding | Every MCP request bound to cell A's certificate as `agent:cell-a` | **PASS** | |
| C-secrets-exist-elsewhere / **G0-agent-holds-no-credentials** | JWT payload and signature, cell key line and provider key searched in agent_a | **PASS** | 0 hits; present in sidecar_a / model-proxy (control) |
| G0-backend-no-agent-credential | The tool server never receives the JWT, an Authorization header or the client cert | **PASS** | |

## Failures found during S8 (fixed upstream, evidence kept)

1. **S6 model proxy, Content-Length defect.** Re-serializing the checked JSON did not update `Content-Length`. If the canonical body was shorter, the provider hung; if it was longer (non-ASCII), the provider read a **truncated** body that differed from what was checked. It was demonstrated in `S6-model/runs/20261016T005448-pre-fix-content-length-2` (T1e/T1f FAIL), fixed, and S6 re-run 33/33 twice. See the S6 VERDICT addendum.
2. **Image dependency conflict.** Installing mitmproxy 12.2.3 into the spike image downgrades `typing_extensions` (4.16.0 → 4.14.0), which breaks the FastMCP 4.1 client in `mandate-mitm:wave3`. S5 and S6 do not use FastMCP; in S8, `agent_a` uses the spike image. A combined image would need dependency resolution.

## Limitations

- **One scripted scenario, no LLM.** Only 4 effects. "Pending approval" is not followed by an approver flow.
- **Timing:** G0 time ordering relies on all containers sharing the Docker Desktop VM kernel clock. It does not hold across hosts without synchronized clocks.
- The PEP's session labels are fixed for the script, not propagated from tool outputs. Label propagation is evaluated only in emulation (S4a).
- The S6 provider is a mock. S6-T9 and S4b are BLOCKED on your decisions.

## Reproduce

```
bash driver/run_s8.sh <label>
```
