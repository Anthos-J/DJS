# MANDATE v3 — Spike execution status (Wave 0–1)

*Run date: 15 Oct 2026. Playbook: [../04_Phase4_Prebuild_Validation_Playbook.md](../04_Phase4_Prebuild_Validation_Playbook.md). Runner: Claude. **Reviewer: not yet assigned.** Under playbook rule 7, no claim can reach SECURITY-TESTED until a second person reviews the evidence.*

## Summary

| Spike | Outcome | Highest status reached |
|---|---|---|
| **S0** Environment | **PASS** (15 Oct, after the user reinstalled Docker Desktop 4.95.0 / Engine 29.8.2). Earlier attempt: BLOCKED by the 4.68.0 startup crash. See `S0-env/VERDICT.md`. | Baseline recorded |
| **S3** Cell isolation | **Playbook topology: FAIL** on T3. From the cell, the internal bridge's gateway IP exposes Docker Desktop VM host-namespace services (rpcbind TCP/UDP 111, TCP 44775). This was not shown to be an egress path. **Remediation R1** (gateway mode `isolated` on cell networks): **all pass/fail criteria PASS** in 2 clean runs. See `S3-isolation/VERDICT.md`. | R1: **LOCALLY REPRODUCED**. Baseline: FAIL. **Not SECURITY-TESTED.** |
| **S1** MCP PEP | **Executed.** Every pass/fail check passed in the second run. | LOCALLY REPRODUCED. See notes on INTEGRATION-VERIFIED. |
| **S2** Cedar + SymCC | **Executed.** All pass/fail checks passed. | LOCALLY REPRODUCED |

**Deviation from instructions:** S1 and S2 ran in a Python 3.14 virtual environment on the Windows host, **not inside containers**, because Docker was unavailable. Neither spike depends on network isolation, so its claims are unaffected. Both must still be re-run in `python:3.12` containers once S0 passes, to satisfy AM5. Versions: fastmcp 4.1.0, mcp 2.3.0, cedarpy 4.12.2 (see `pip_freeze.txt`), cedar-policy-cli 4.13.0 experimental (SHA-256 matches the published value), cvc5 1.3.1 (static Win64 build; no published hash, ours recorded below).

## S1 results (`S1-pep/runs/20261015T042718-host-venv-rerun`)

| Test | Verdict | Evidence (independent observation = backend raw request log + `writes.log`) |
|---|---|---|
| T1 middleware runs on proxied call, result modified before client | PASS | Client got `["doc-text","[PEP-MARK]"]`; backend saw `read_doc` |
| T2 block prevents backend execution | PASS | Client `isError` "DENY: policy"; backend saw **no** `write_record`; `writes.log` unchanged |
| T3 argument rewrite reaches backend | PASS | Backend wrote `a-mod` |
| T4 `forward_incoming_headers=False` stops credential forwarding | PASS | Backend `authorization` = none |
| T4 positive control (default config) | PASS | Backend received `Bearer CANARY-AUTH-7f3a`. **Default forwarding of the agent's credential is reproduced (F1).** |
| T5 client `_meta` forwarded upstream | RECORDED | Backend received `x-evil`, `traceparent`, `progressToken`, `logLevel`. **Confirms F1.** Stripping was not attempted (open item R2). |
| T6 tool-name aliases | PASS | 7 aliases (case, trailing space, prefix, fake hash, zero-width space, NUL) all denied; zero backend calls |
| T7 legacy (handshake) and auto eras | PASS | Identical enforcement in both |
| T8 20 concurrent mixed calls | PASS (2nd run) | Exactly the 10 allowed writes. 1st run: a lost line was traced to the **test backend's** unsynchronized file append. The backend request log showed all 10 allowed calls and 0 forbidden. Harness fixed and suite re-run. |
| T9 blocked-call form | RECORDED | Tool result with `isError: true` and text "DENY: policy" (not a JSON-RPC error) |
| T10 middleware ordering | RECORDED, **finding** | Second middleware added *after* the PEP mutated arguments **after** the check, and the backend received `MUTATED-AFTER-CHECK`. That is a check-then-change (TOCTOU) gap. When the PEP is added **last** (innermost), it checks exactly what is forwarded. **Rule: the PEP must be the last-added (innermost) tool-call middleware, or the only one.** |
| T11 latency (100 calls, localhost) | RECORDED | PEP p50 27.6 ms / p99 53.8 ms vs direct p50 4.0 ms / p99 6.9 ms (fresh backend session per request) |

**Status note.** The client → PEP → backend path crosses real HTTP hops between processes, but all on localhost with no TLS, no sidecar and no isolation. Ledger items 1–4 are therefore recorded as **LOCALLY REPRODUCED**. They become INTEGRATION-VERIFIED when re-run in the S8 topology. Items 5 and 7 cannot be SECURITY-TESTED until the clean-environment rerun and second-person review.

## S2 results (`S2-cedar/runs/`)

| Test | Verdict | Evidence |
|---|---|---|
| T1 schema validation (+ negative control) | PASS | `P` validates; undeclared `context.nonexistent_attr` rejected |
| T2 bounded exhaustive two-pass vs independent oracle | **PASS, 4,608 / 4,608** | 0 mismatches, 0 errors (~10k evaluations/s) |
| T3a missing attribute, no schema (unforced) | RECORDED | **Allow, no errors.** Conditions stopped early (`&&` short-circuited), so the missing attribute was never evaluated. Missing attributes can go unnoticed without a schema. |
| T3c missing attribute, no schema, forced evaluation | PASS, **finding** | **Decision = Allow** with error *"record does not have the attribute `approved`"*. The G3a forbid errored, was skipped, and the permit won. **Reproduces the skip-on-error risk: the PEP must deny on any error.** |
| T3b missing attribute **with** schema | PASS, **finding** | Decision = **`NoDecision`** (not `Deny`) with a request-build error. **The PEP must test `decision == Allow and not errors`, never `decision != Deny`.** |
| T4 SymCC `implies` | PASS | `P ⇒ Q_G3a` **VERIFIED** for (Agent, send, Sink) and (Agent, read, Resource). Seeded `P_bad` → **DOES NOT HOLD**, with a counterexample. |
| T4 tooling findings | RECORDED | (a) The CLI **exits 0 even when the property does not hold**, so CI must parse the verdict text. (b) Counterexamples use out-of-range values (conf −1, clearance −2, threshold 2⁶³−1), because SymCC reasons over all 64-bit integers, which is stronger than our 0–3 abstraction. The PEP must range-check label values. (c) Checks run per principal-type / action / resource-type environment; cvc5 is found via `--cvc5-path` or `CVC5`. **This closes open item R1.** |
| T5 cedarpy 4.12.2 vs CLI 4.13.0 differential | PASS | 300 random samples: 0 mismatches (207 Deny / 93 Allow). This is a sample, not the full corpus. |
| T6 throughput | RECORDED | ~7,300 single requests/s with pre-parsed handles (host Python, single thread) |

cvc5 zip SHA-256 (ours): `e1e183f50f1bbd9d10b2dc6ab9574cb9fa02acfdc1957f43040db3529f92b94e`. Size matches the GitHub release asset (41,130,843 bytes).

## Ledger update (playbook §7)

| # | Claim | Before | Now |
|---|---|---|---|
| 1 | Middleware runs for proxied calls | DOCUMENTED | **LOCALLY REPRODUCED** |
| 2 | Block prevents backend execution | DOCUMENTED | **LOCALLY REPRODUCED** |
| 3 | Argument rewrite | DOCUMENTED | **LOCALLY REPRODUCED** |
| 4 | Result modification before client | DOCUMENTED | **LOCALLY REPRODUCED** |
| 5 | No `Authorization` forwarding with `False` (forwarded by default) | DOCUMENTED | **LOCALLY REPRODUCED**, with positive control. Awaiting review + clean rerun for SECURITY-TESTED. |
| 6 | `_meta` forwarded / strippable | DOCUMENTED / UNVERIFIED | Forwarding **LOCALLY REPRODUCED**; stripping UNVERIFIED |
| 7 | No alias bypass | UNVERIFIED | **LOCALLY REPRODUCED** (7 aliases). Awaiting review + rerun. |
| 8 | Enforcement in client protocol era | UNVERIFIED | **LOCALLY REPRODUCED** (legacy and auto) |
| 9 | Safe middleware ordering rule | UNVERIFIED | **LOCALLY REPRODUCED:** PEP innermost or only |
| 10 | cedarpy decision / reasons / errors | DOCUMENTED | **LOCALLY REPRODUCED** |
| 11 | Two-pass = truth table | UNVERIFIED | **LOCALLY REPRODUCED** (exhaustive, 4,608 cases) |
| 12 | Errors → DENY rule demonstrable | UNVERIFIED | **LOCALLY REPRODUCED** (T3c shows it is necessary) |
| 13 | SymCC proof + counterexample | DOCUMENTED | **LOCALLY REPRODUCED** |
| 14 | cedarpy ≡ CLI | UNVERIFIED | **LOCALLY REPRODUCED** (300-sample) |
| 15–21 | Cell isolation claims | DOCUMENTED / UNVERIFIED | Unchanged (S3 not run) |

## Design consequences (add to playbook amendments)
- **AM8:** The PEP must be the last-added (innermost) tool-call middleware, or the only one. Otherwise arguments can change after the check (S1-T10).
- **AM9:** PEP decision rule = `decision == Allow and diagnostics.errors == []`. Request validation can return `NoDecision`. Always evaluate with the schema (S2-T3a/b/c).
- **AM10:** SymCC in CI must parse the verdict text (exit code is 0 on failure). The PEP must range-check every label attribute before evaluation (S2-T4).

## To unblock S0 / S3 (your action)
Docker Desktop's own error dialog offers only *Quit* or *Reset to factory defaults*. A narrower fix, which I could not apply under this session's permissions:
1. Quit Docker Desktop.
2. Delete the two 0-byte stale socket files in `%LOCALAPPDATA%\Docker\run\` (`dockerInference`, `userAnalyticsOtlpHttp.sock`). If Explorer refuses, run `fsutil reparsepoint delete <file>` first, or reboot and try again.
3. Start Docker Desktop.

Also note: **only ~5.9 GB free on C:**. Wave 1–2 images (netshoot, python, nginx, mitmproxy) plus the Docker VM should fit, but it is tight.

## S3 results (15 Oct 2026, evening). Full detail: `S3-isolation/VERDICT.md`

| Criterion | Playbook topology (baseline) | R1: `gateway_mode_ipv4/ipv6: isolated` |
|---|---|---|
| T1 no direct IPv4 egress | PASS | PASS |
| T2 no DNS resolution / exfiltration (pcap method; canary not approved) | PASS | PASS |
| T3 no host / gateway-IP / Desktop-internal services | **FAIL**: rpcbind TCP/UDP 111 and TCP 44775 on gateway IP | PASS |
| T4 no IPv6 path (control n/a: host has no IPv6 egress) | PASS | PASS |
| T5 intended gateway path works | PASS | PASS |
| T6 sidecar secrets / processes invisible | PASS | PASS |
| T7 no NET_ADMIN/NET_RAW; caps 0; no-new-privileges; read-only | PASS | PASS |
| T8 metadata-style service unreachable (local fixture; real 169.254.169.254 never contacted) | PASS | PASS |
| T9 cross-cell isolation | PASS | PASS |

Every negative probe is paired with a positive control, and all controls passed in the final runs. Harness errors found and fixed during the run (netcat `-e`, probe timeouts, subnet-dependent pcap filter, a vacuous T3e) are documented and were **not** counted as isolation results.

### Ledger update (playbook §7)

| # | Claim | Now |
|---|---|---|
| 15 | No direct IPv4 egress | LOCALLY REPRODUCED (baseline and R1) |
| 16 | No DNS resolution / exfiltration | LOCALLY REPRODUCED (pcap evidence) |
| 17 | Host / gateway-IP services unreachable | **FAIL in playbook topology**; LOCALLY REPRODUCED with R1 |
| 18 | No IPv6 path | LOCALLY REPRODUCED (IPv6 disabled in cell; weak positive control) |
| 19 | Sidecar secrets unreadable | LOCALLY REPRODUCED |
| 20 | No NET_ADMIN / NET_RAW | LOCALLY REPRODUCED |
| 21 | Cross-cell isolation | LOCALLY REPRODUCED |

### New design amendment
- **AM11:** Cell networks **must** be `internal: true` **and** use bridge gateway mode `isolated` (`com.docker.network.bridge.gateway_mode_ipv4/ipv6: isolated`). A plain internal network exposes the container host's namespace services through the bridge address (S3-T3 baseline FAIL). A cell network must contain only the cell and the gateway (T9c).

### Still required before S3 can be SECURITY-TESTED
1. Clean-environment rerun of the R1 variant on a second machine or after a Docker reset.
2. Independent review of `S3-isolation/` evidence by a second person.
3. Optionally, a UDP sweep of host-side addresses (only TCP full sweep + UDP 111 were run).
