# S7 Credential binding at the PEP: verdict

**Runs:**
- `runs/20261015T230514-run5`: 38 PASS / 0 FAIL / 0 HARNESS-ERROR.
- `runs/20261015T230728-run6`: 38 PASS / 0 FAIL / 0 HARNESS-ERROR, a full reproduction with freshly generated PKI and tokens.

**Status:** **LOCALLY REPRODUCED.** Ledger 22 and 25 are **INTEGRATION-VERIFIED** for this topology. **Not SECURITY-TESTED**: the clean-environment rerun and independent review are outstanding.
**Runner:** Claude. **Reviewer:** not assigned.

## Prerequisites (checked before S7 ran)

| Prerequisite | State |
|---|---|
| S1 PEP | PASS in pinned containers, 3 runs (`S1-pep/runs/*-container-run*`) |
| S3 cell profile | Canonical AM11 profile LOCALLY REPRODUCED; tag `s3-am11-local-repro` |
| AM11 gate on the S7 topology | Static check exit 0, runtime check exit 0 in every run (`cell_policy_*.json`). The gate runs before any test |

## Topology (`config/compose.yaml`; deployed only through `driver/run_s7.sh`)

```
agent_X ──(shared netns)── sidecar_X nginx 127.0.0.1:8081 ──mTLS (cell cert) + Bearer JWT──► terminator nginx :8443
   (cap_drop ALL, read-only,      holds cell.crt/key + JWT        cellnet_X (AM11)             ssl_verify_client on; X-Client-Cert = $ssl_client_escaped_cert
    no secrets, no volumes                                                                     │ pepnet (internal; terminator + PEP only)
    except read-only test code)                                                                ▼
                                                                    PEP (pep_bound.py): binding check on EVERY HTTP request → S1 proxy PEP (allowlist, FWD=false, innermost)
                                                                                               │ toolnet (internal; PEP + backend only)
                                                                                               ▼
                                                                    backend (FastMCP; holds a dummy downstream key; logs every raw request)
```

- **Cells:**
  - A: cert A + JWT_A, the approved path;
  - B: cert B + JWT_B, the positive control;
  - C: cert B + **JWT_A**, the playbook T2 placement.
- **Test PKI:** a one-shot container creates the test CA, terminator server certificate, cell certificates, ES256 issuer key and tokens fresh on every run. Each component's secrets go only into that component's volume. Volumes are deleted at teardown; only public data (thumbprints, claims, token prefixes) is kept in `pki_public.json`.
- **Binding rule (PEP):** a request is allowed only if all of these hold:
  - exactly one `X-Client-Cert` and exactly one `Authorization: Bearer` header;
  - the certificate chains to the test CA;
  - the JWT verifies with ES256 against the issuer key, and `iss`, `aud`, `exp`, `iat`, `sub`, `sid` and `cnf` are all present and valid;
  - `sid` is not revoked;
  - `cnf.x5t#S256 == base64url(SHA-256(DER(cert)))`.

  The identity (`sub`) comes only from a verified, bound token. The check runs before the MCP layer, so `initialize`, `list` and `call` are all covered.

## Results (run5; run6 identical verdicts)

Independent observation: rejections are judged at the backend (no tool call arrives) and, for terminator-level rejections, at the PEP (nothing arrives). The PEP's own log is used only to show *why* it decided.

| ID | Test | Result | Evidence |
|---|---|---|---|
| T1 | Agent A → sidecar → terminator → PEP → backend `echo` | **PASS** | Client `echo-ok`. PEP binding log: `binding match`, cert x5t = cell A, `sub agent:cell-a`, `sid sess-A-1`. Tool-layer identity `agent:cell-a`. Backend received exactly `echo` |
| T2-ctl | Cell B with its own token | **PASS** | Accepted and bound to cert B |
| T2 | **JWT_A in a sidecar holding cert B (cell C)** | **PASS** | Rejected, `cnf mismatch` (token bound to A, cert B presented). Backend received **no** tool call |
| T2 matrix | cert B + JWT_A; cert A + JWT_B (from the test fixture) | **PASS** | Both HTTP 401 `cnf mismatch`; no backend call. Controls cert A + JWT_A and cert B + JWT_B were accepted |
| T3 | Agent A → terminator directly: no certificate / self-signed `CN=cell-a` certificate / plain HTTP | **PASS** (3/3) | Terminator `400 Bad Request`; **0 PEP log lines** during the attempt. The fixture's no-cert and rogue-cert attempts with a valid JWT_A also got 400 and never reached the PEP |
| T4a | Agent sends its own `X-Client-Cert` (cert B) through the sidecar | **PASS** | The PEP saw only cert A's thumbprint. The terminator overwrote the header, and the call stayed bound to cell A |
| T4b | Agent sends its own `Authorization: Bearer JWT_B` through the sidecar | **PASS** | The PEP saw only `sid sess-A-1` / `agent:cell-a`; the sidecar replaced the header |
| T4c | Fixture: cert A + JWT_B + forged `X-Client-Cert` (cert B) | **PASS** | 401 `cnf mismatch`: the forged header was overwritten, so JWT_B did not match |
| T4d | Two `Authorization` headers | **PASS** | Terminator (nginx) answered 400 before the PEP; nothing reached the PEP |
| T4e | Agent → PEP / backend by name and by every IP | **PASS** (5/5) | By name: name resolution fails. By IP: `Network is unreachable` |
| T4f | Test network → PEP by name and IP | **PASS** (3/3) | Unreachable; only the terminator reaches the PEP |
| T5-ctl | Secrets exist elsewhere (positive control) | **PASS** | JWT_A payload in sidecar_a `/secrets/auth.conf`; key line in `/secrets/cell.key`; downstream key in the backend env |
| T5 | Agent A environment, filesystem and `/proc` searched for JWT_A payload and signature, cell A and B key lines, downstream key | **PASS** | 0 hits; `/secrets` absent; visible processes are only the agent's own. Patterns arrive on stdin, so they are not in the scanner's own cmdline |
| T5b | Downstream confinement | **PASS** | Across 89 backend requests: 0 contain the JWT, an `Authorization` header or `x-client-cert` |
| T6 | Streaming through both nginx hops and the PEP | **PASS** (functional) | 5 progress events at 0.88 / 1.48 / 2.09 / 2.69 / 3.29 s, about 0.6 s apart as emitted; incremental |
| T7 | Expired, revoked-sid, tampered, `alg=none`, rogue issuer, wrong audience, missing `cnf`, no token | **PASS** (8/8) | Each HTTP 401 with the matching reason; no backend call |
| T7-runtime | Revoke the live `sess-A-1`, then restore | **PASS** | Next call rejected (`session revoked`), then accepted again after removal |

## Harness errors (not counted; kept with NOTE files)

1. **run1:** the driver crashed while reading a log mid-run. No verdicts were produced.
2. **run2:** the driver did not compile, because my edit turned `\n` into a literal newline. No tests ran.
3. **run3 (verdicts not used):**
   - The driver read logs through a helper that trimmed output to 3,000 characters, so per-test log deltas were wrong.
   - T4d evaluated the single-header MCP call instead of the duplicate-header request.
   - T5's generic `PRIVATE KEY` pattern matched `/usr/bin/sqv` and the agent's own throwaway rogue key from T3.
4. **run4:** the key-search pattern spanned a PEM line break and could never match. The **positive control caught this** (T5-ctl FAIL), and the agent scan was correctly not credited (HARNESS-ERROR). The other 36 checks passed. Fixed in run5.

## What this establishes / does not

- **Establishes, for this topology, these images and these versions** (nginx 1.29.8 `sha256:56168782…`; spike image `sha256:44bc7e00…`):
  - the PEP accepts a session credential only with the certificate its `cnf.x5t#S256` names;
  - cross-cell replay, header spoofing, sidecar bypass and invalid tokens are rejected;
  - the agent container holds neither the credential nor the key;
  - the backend never receives them;
  - streaming survives both hops.
- **Does not establish:**
  - protection if the **sidecar** is compromised. Accepted in v3: a live compromised cell can use its sidecar;
  - production PKI, rotation or key-storage hardening;
  - revocation latency at scale. The list is re-read on every request.
- **Not SECURITY-TESTED:** that needs a clean-environment rerun on another machine and a second-person review. Both runs used the same Docker engine.

## Reproduce

```
bash driver/run_s7.sh <label>      # AM11 static check -> up -> AM11 runtime check -> tests -> evidence -> teardown
```
