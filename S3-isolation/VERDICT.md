# S3 Execution-cell isolation: verdict

**Platform:** Docker Desktop 4.95.0, Engine 29.8.2 (linux/amd64, WSL2 kernel 6.6.87.2), Compose v5.6.0. Images pinned by digest (`config/.env`).
**Runner:** Claude. **Independent reviewer:** not yet assigned. **No claim here is SECURITY-TESTED** (playbook rule 7).

## Outcome

| Configuration | Result | Runs |
|---|---|---|
| **Baseline**: playbook topology (`config/compose.yaml`; `internal: true` cell networks) | **FAIL**, criterion T3: host-namespace services are reachable from the cell | `runs/20261015T192937-baseline`, `runs/20261015T193623-baseline-final`, `runs/20261015T204143-baseline-rerun2`, `runs/20261015T205809-baseline-regression` (T3 set reproduced; positive-control flake, see harness error 7), `runs/20261015T210213-baseline-regression` (**5 reproductions**). Kept as regression fixture `config/compose.yaml`. |
| **Remediation R1**: same topology + `com.docker.network.bridge.gateway_mode_ipv4/ipv6: isolated` on the cell networks (`config/compose.isolated.yaml`; only those 6 lines differ) | **All pass/fail criteria PASS.** Status **LOCALLY REPRODUCED** | `runs/20261015T193842-R1-final-run1`, `runs/20261015T194057-R1-final-run2`, `runs/20261015T204359-R1-rerun3` (3 runs, each from full teardown). Superseded by the canonical AM11 profile below. |
| **Canonical AM11 profile** (`config/compose.cell.yaml`, deployed through the fail-closed gate `harness/deploy_cells.sh`) | **All pass/fail criteria PASS**, 46 PASS / 0 FAIL / 0 HARNESS-ERROR. Status **LOCALLY REPRODUCED** | `runs/20261015T210003-canonical`, `runs/20261015T210358-canonical` (inside regression runs `20261015T205803-regression` and `20261015T210203-regression`) |

### The failure (baseline)
- From inside `agent_a` (`cap_drop: ALL`, read-only, no-new-privileges), the internal network's bridge gateway IP accepts connections on **TCP 111 (rpcbind), TCP 44775 and UDP 111**.
- These are services in the **Docker Desktop VM host namespace**: `ss -ltnup` shows them bound to `0.0.0.0`/`[::]` (`vm_host_listeners.txt`).
- Docker documents that a normal internal network keeps a bridge address that containers can reach.
- The original 10-port T3d probe **missed this**. It was found by a full 65,535-port sweep added during the run.
- **Not demonstrated as an egress path:**
  - HTTP `GET` and `CONNECT` relay attempts through both ports returned 0 bytes.
  - A host-namespace capture during those attempts recorded **0 outbound non-private packets** (`T3f_proxy_test.txt`).
- **It is still a FAIL** of the stated criterion ("no host or gateway-IP service reachable"). It exposes VM host RPC services to an untrusted cell. Whether they can be exploited was not tested.

### Why R1 fixes it (evidence, not assumption)
- With gateway mode `isolated`, the host-side cell bridges carry **no IPv4 address**, only IPv6 link-local (`host_vm_interfaces.txt`). The baseline bridges carry `.1/16`.
- The `.1` address is then given to a container. In run 2 it went to the gateway container (only port 8080 open, which is the intended path); in run 1 to the cell's own sidecar. The holder is recorded in `context.json`.
- IPv6 is disabled on the cell interface (`disable_ipv6=1`), and a TCP attempt to the host bridge's link-local address on port 111 failed (`R1_followup.txt`).

## Rerun 3 (15 Oct, 20:41–20:46, after the S0 recheck)
- **Baseline `20261015T204143-baseline-rerun2`:** 43 PASS / 3 FAIL / 9 INFO / 0 HARNESS-ERROR.
  - Same failure: T3e (TCP 111 + a high port), T3f (UDP 111) and T3g, at bridge address 172.20.0.1.
  - The high port is now **55953**, not 44775. It is a dynamically assigned host-namespace listener, not a fixed service.
- **R1 `20261015T204359-R1-rerun3`:** 46 PASS / 0 FAIL / 9 INFO / 0 HARNESS-ERROR.
  - `.1` held by a **third** holder, `privctl_a`. No allowed ports; the strict full sweep found 0 open (2.8 s).
  - The only host bridge with IPv4 is `edge` (172.20.0.1/16, not a cell network). T3g shows it is unreachable from the cell on 111.
  - Cell capture: 0 off-subnet packets, 0 IPv6. Host-VM capture: cell DNS probe name 0×, control 1×.
- **Outcome:** both verdicts are unchanged. This is a same-machine rerun; see the S0 freshness caveat. It does **not** satisfy the clean-environment rerun or the independent review.

## AM11 made mandatory: canonical profile, fail-closed gate, regression suite (15 Oct, 20:50–21:08)

**Decision (user, 15 Oct):** AM11 is mandatory for every MANDATE execution-cell network in the reference deployment profile, and only for those networks.

### What changed

**`config/compose.cell.yaml`** is the canonical profile:
- A reusable `x-mandate-cell-network` template: bridge driver, `internal: true`, `enable_ipv6: false`, both gateway modes `isolated`.
- `mandate.role` labels on every service and on the cell networks.
- Test fixtures moved off cell networks:
  - `privctl_a` moved to the non-cell network `ctlnet`. It is still the T7 positive control; that control is unchanged.
  - `neighbour_a2` removed. It existed only for the **INFO** probe T9c, which showed that same-network peers are reachable; AM11 now forbids such peers and the checker enforces it. No pass/fail criterion was removed.

**`harness/cell_policy.py`** is the AM11 checker. Rules are listed in `config/README.md`.
- **Static mode** checks the resolved Compose model before `up`.
- **Runtime mode** checks `docker network inspect` / `docker inspect` and the host-VM `ip -4 addr` after `up`:
  - effective `Internal` and `Options`;
  - no IPAM gateway;
  - no IPv4 on the host-side `br-<id>`;
  - exact membership: one sidecar plus the gateway;
  - agent `NetworkMode container:<sidecar>`, CapDrop ALL, read-only root filesystem, no-new-privileges.
- Cell networks are also detected **structurally** (any service whose network namespace is shared), so removing labels does not opt a cell out.

**`harness/deploy_cells.sh`** is the fail-closed gate:
- static violation → refused, nothing created (exit 3);
- runtime violation → torn down (exit 4);
- checker or `up` error → torn down (exit 2).

`harness/run_variant.sh` now deploys through the gate by default. Only the `regression-fixture` mode bypasses it, and only for the baseline.

### Docker prerequisite check (`runs/20261015T205246-prereq-gateway-mode/prereq.log`, Engine 29.8.2)

| Attempt | Docker result |
|---|---|
| `gateway_mode_ipv4=isolated` without `--internal` | **rejected**: "gateway mode 'isolated' can only be used for an internal network" (exit 1) |
| `gateway_mode_ipv6=isolated` without `--internal` (with and without `--ipv6`) | **rejected**, same message |
| `--internal` + both `isolated` | accepted. Effective options show both `isolated`; IPAM has **no Gateway** |
| mode value `bogus` | rejected: "unknown gateway mode" |
| **misspelled key** `gatway_mode_ipv4=isolated` with `--internal` | **accepted silently (exit 0)**. The network gets a host-side gateway `172.21.0.1`, i.e. the baseline T3 exposure |

Docker enforces "isolated requires internal" but **not** "internal requires isolated". It also does not catch a misspelled key. The checker enforces both and rejects unknown option keys.

### Regression suite: `bash harness/regression.sh`. Clean run `runs/20261015T210203-regression` (0 failing assertions)

| ID | Assertion | Result | Evidence |
|---|---|---|---|
| R1 | 24 checker mutation cases, one per rule. Each non-compliant model is rejected for the expected reason; the unmutated canonical model is accepted | **PASS** 24/24 | `R1-checker/checker_mutation_results.json` |
| R2-typo | Misspelled-key profile is **refused** before `up` for the expected reason; 0 containers created | **PASS** | `R2-typo/` |
| R2-no-isolated | Profile without the AM11 options is **refused**; 0 containers created | **PASS** | `R2-no-isolated/` |
| R3a | Original topology (regression fixture) **still FAILS T3** with exactly T3e/T3f/T3g. `172.19.0.1` exposes TCP 111, TCP 55953 and UDP 111. 0 harness errors | **PASS** (failure reproduced, as required) | `runs/20261015T210213-baseline-regression` |
| R3b | The runtime checker flags the baseline's effective state: no `isolated` options, IPAM gateway present, host bridge carries `172.19.0.1/16` | **PASS** | `.../cell_policy_runtime.json` |
| R4a | Canonical profile passes the gate (static exit 0, `up` exit 0, runtime exit 0) | **PASS** | `runs/20261015T210358-canonical/deploy.log` |
| R4b | Canonical full S3 suite: 0 FAIL, 0 HARNESS-ERROR; T5 approved gateway path PASS | **PASS** (46 PASS, 8 INFO) | `.../results.jsonl` |
| R5 | Runtime drift: `docker network connect` of a foreign container to `cellnet_a` is flagged (exit 3, "forbidden members"); after disconnect, compliant again (exits 0/3/0) | **PASS** | `R5-*.json` |

R5 shows the checker *detects* drift after deployment. Nothing runs it continuously yet; that is noted as residual risk.

### Canonical profile: per-criterion evidence (`runs/20261015T210358-canonical`)

| ID | Result | Evidence |
|---|---|---|
| Effective network settings | compliant | `cellnet_a`/`cellnet_b`: `Internal=true`, `EnableIPv6=false`, both gateway modes `isolated`, IPAM `{Subnet}` only (no Gateway). Host bridges `br-56a2a7741e24` / `br-d3fde78243ec` carry **only IPv6 link-local** (`host_vm_interfaces.txt`). Members are exactly `{sidecar, gateway}`. The bridges that do carry IPv4 belong to the non-cell networks `edge` and `ctlnet` |
| T1 IPv4 egress | **PASS** | Positive controls passed. Cell routes: own /16 only, no default route. Cell capture: 0 off-subnet packets |
| T2 DNS | **PASS** | Resolver SERVFAIL. Host-VM capture: cell probe name 0×, control name 1× (forwarded). T2-alt pcap method |
| T3 host / gateway-IP | **PASS** | `.1` held by the **gateway container**; full TCP sweep shows only `8080` (approved). UDP 111 closed; 111 closed on all known host-side addresses; Desktop names do not resolve; proxy 3128 unusable |
| T4 IPv6 | **PASS** | No global IPv6 address; 0 IPv6 packets in the cell capture. **Weak positive control:** `outside` has no IPv6 egress either (C-T4 INFO, curl rc 7) |
| T5 intended path | **PASS** | `curl gateway:8080/echo` → `gateway-ok`. Approved route intact |
| T6 sidecar secrets | **PASS** | Secret absent from the agent; filesystem grep found nothing; sidecar processes invisible |
| T7 capabilities | **PASS** | CapEff/CapPrm/CapBnd 0; `ip link set` and `tcpdump` denied; NoNewPrivs=1; read-only root filesystem. Positive control `privctl_a` succeeded |
| T8 metadata (local fixture) | **PASS** | Fixture unreachable by name and IP; no route to 169.254.169.254 (lookup only; never contacted) |
| T9 cross-cell | **PASS** | agent_a → sidecar_b fails (control passes); agent_b cannot reach cell A's loopback |

## Criteria (earlier R1 runs)

| ID | Criterion | Baseline | R1 (both runs) | Positive control | Evidence / notes |
|---|---|---|---|---|---|
| T1 | No direct IPv4 egress (HTTPS, TCP 1.1.1.1:443, TCP 8.8.8.8:53, ICMP, edge-network peer) | PASS | **PASS** | `outside` reached HTTPS 200 and TCP 1.1.1.1:443 | Cell route table has only its own /16 and **no default route**. Cell capture: **0 packets to any destination outside its own subnet**. |
| T2 | No DNS resolution or exfiltration | PASS | **PASS** | Control query `s3probe-<rand>-ctl.example.com` **visible** in host-VM capture (forwarded to 192.168.65.7) | Cell probe name appears **0 times** in the host-VM capture. Resolver answers SERVFAIL in 0 ms; `example.com` gets no answer; direct `@1.1.1.1` fails with "network unreachable". **Deviation:** pcap method (T2-alt) used instead of a canary service, which has not been approved. |
| T3 | No host / gateway-IP / Desktop-internal services | **FAIL** (T3e TCP 111 & a dynamic high port: 44775, later 55953; T3f UDP 111, T3g) | **PASS** | `outside` resolves `host.docker.internal` and reaches `http.docker.internal:3128` | Desktop names do not resolve in the cell; using the internal proxy `http.docker.internal:3128` as egress fails; full TCP sweep of `.1` finds no host-side listener |
| T4 | No IPv6 path | PASS | **PASS** | **Not applicable:** `outside` also has no IPv6 egress | No global IPv6 address; `disable_ipv6=1` on eth0; 0 IPv6 packets in the cell capture. Evidence that IPv6 is *blocked* rests on it being disabled in the cell, not on a failed-reachable path. |
| T5 | Intended path works | PASS | **PASS** | — | `curl gateway:8080/echo` → `gateway-ok` |
| T6 | Sidecar secret and processes invisible | PASS | **PASS** | Sidecar reads `/secrets/cell.key` | Agent: file absent; filesystem-wide grep finds nothing; `ps` shows only the agent's own processes |
| T7 | No NET_ADMIN / NET_RAW; hardening | PASS | **PASS** | `privctl_a` (with caps) can `ip link set` and open a capture | Agent: CapPrm/CapEff/CapBnd all 0; `ip link set` and `tcpdump` denied; NoNewPrivs=1; read-only root filesystem |
| T8 | Metadata-style service unreachable | PASS | **PASS** | `outside` reads the fixture's `FAKE-NOT-A-SECRET` | Local fixture unreachable by name and by IP. `ip route get 169.254.169.254` → no route (routing-table lookup only). **The real metadata address was never contacted.** |
| T9 | Cross-cell isolation | PASS | **PASS** | Gateway reaches `sidecar_b`; agent_a reaches its own loopback sidecar | agent_a → sidecar_b fails; agent_b cannot reach cell A's loopback listener |

### Recorded, not criteria (INFO)
- **T9c:** a peer on the **same** internal network (`neighbour_a2`) **is reachable**. Design rule: a cell network must contain only the cell and the gateway.
- **C-T3-proxy3128:** normal containers can reach Desktop's internal proxy on port 3128. The cell cannot.

## Harness errors (distinguished from isolation results)
1. **Run 1 (`runs/20261015T191716`):** OpenBSD netcat in netshoot has no `-e`, so the listeners never started. Two positive controls failed, and the dependent T9 negatives were auto-marked HARNESS-ERROR and not credited. Fixed with `socat`. Run kept with `NOTE_harness_error.txt`.
2. **T3 probes hit the 40 s harness timeout** while unresolvable names hung. Fixed with per-name `timeout`.
3. **`runs/20261015T192937-baseline/pcap_analysis.txt`** used fixed subnets; Docker renumbered the networks, so those counts are **invalid**. Re-analyzed with `harness/analyze_pcap.py` (subnets read per run); see `pcap_analysis.json`.
4. **`runs/20261015T192427-rerun`** had all pass/fail criteria pass, but it predates the full-sweep probes, so it is not used for the T3 verdict. **`runs/20261015T193236-R1-isolated-gateway`** is superseded for the same reason (vacuous T3e; see item 5).
6. **`runs/20261015T205657-regression` (aborted):** in `regression.sh`, `down_all()` reused the loop variable `f`, so R2 deployed a nonexistent file and was refused for the wrong reason (checker exit 2). Fixed: the variable is now local, and R2 must match the *expected* violation and contain no `checker_error`. NOTE file in the run.
7. **`runs/20261015T205803-regression`, R3a failed:** the positive control C-T1a (`outside` → `https://example.com`) timed out (curl rc 28) while C-T1b passed. The harness correctly withheld credit for T1a (HARNESS-ERROR). The T3 failure set itself reproduced exactly. This is an environment / positive-control failure, not an isolation result. The whole suite was re-run clean (`20261015T210203-regression`). NOTE file in the run.
5. **The first T3e for R1 was vacuous**: with no gateway IP, the probe exited without testing anything. Replaced by a strict sweep of the subnet's `.1` with a holder-aware allowlist. Final runs use this version.

## What this does and does not establish
- **Establishes (LOCALLY REPRODUCED):** on this exact platform and versions, the R1 cell topology confines a hardened agent container across every probe listed above. The baseline playbook topology does **not** (T3).
- **Does not establish:**
  - SECURITY-TESTED status (needs a clean-environment rerun on a reviewer's machine and independent review);
  - resistance to container escape or kernel exploits;
  - UDP services other than 111 on the host side (only a TCP full sweep plus UDP 111 were run);
  - behavior under other Docker Desktop versions or Linux Docker Engine;
  - side channels;
  - IPv6-enabled cell networks (the profile forbids them; the checker rejects `enable_ipv6`);
  - continuous drift monitoring. The runtime check runs at deploy time; R5 shows it detects drift when it is run.

## Reproduce

```
bash harness/regression.sh                                         # full suite R1-R5; expected: 0 failing assertions
bash harness/deploy_cells.sh compose.cell.yaml                     # canonical deploy through the AM11 gate
bash harness/run_variant.sh compose.cell.yaml canonical            # gated deploy + full S3 probes
bash harness/run_variant.sh compose.yaml baseline regression-fixture   # expected: FAIL T3e/T3f/T3g
```
