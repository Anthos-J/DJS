# S3 Execution-cell isolation: verdict

**Platform:** Docker Desktop 4.95.0, Engine 29.8.2 (linux/amd64, WSL2 kernel 6.6.87.2), Compose v5.6.0. Images pinned by digest (`config/.env`).
**Runner:** Claude. **Independent reviewer:** not yet assigned. **No claim here is SECURITY-TESTED** (playbook rule 7).

## Outcome

| Configuration | Result | Runs |
|---|---|---|
| **Baseline**: playbook topology (`config/compose.yaml`; `internal: true` cell networks) | **FAIL**, criterion T3: host-namespace services are reachable from the cell | `runs/20261015T192937-baseline`, `runs/20261015T193623-baseline-final`, `runs/20261015T204143-baseline-rerun2` (3 reproductions) |
| **Remediation R1**: same topology + `com.docker.network.bridge.gateway_mode_ipv4/ipv6: isolated` on the cell networks (`config/compose.isolated.yaml`; only those 6 lines differ) | **All pass/fail criteria PASS.** Status **LOCALLY REPRODUCED** | `runs/20261015T193842-R1-final-run1`, `runs/20261015T194057-R1-final-run2`, `runs/20261015T204359-R1-rerun3` (3 runs, each from full teardown) |

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

## Criteria (final runs)

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
5. **The first T3e for R1 was vacuous**: with no gateway IP, the probe exited without testing anything. Replaced by a strict sweep of the subnet's `.1` with a holder-aware allowlist. Final runs use this version.

## What this does and does not establish
- **Establishes (LOCALLY REPRODUCED):** on this exact platform and versions, the R1 cell topology confines a hardened agent container across every probe listed above. The baseline playbook topology does **not** (T3).
- **Does not establish:**
  - SECURITY-TESTED status (needs a clean-environment rerun on a reviewer's machine and independent review);
  - resistance to container escape or kernel exploits;
  - UDP services other than 111 on the host side (only a TCP full sweep plus UDP 111 were run);
  - behavior under other Docker Desktop versions or Linux Docker Engine;
  - side channels.

## Reproduce

```
bash harness/run_variant.sh compose.yaml baseline              # expected: FAIL T3e/T3f/T3g
bash harness/run_variant.sh compose.isolated.yaml R1-rerun     # expected: all pass/fail criteria PASS
```
