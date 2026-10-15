# S5 HTTP egress enforcement (mitmproxy 12.2.3): verdict

**Runs:**
- `runs/20261015T232913-run2` and `runs/20261015T233103-run3`: 23/23 driver checks PASS, plus the DNS check PASS, in each.
- `runs/20261015T232707-run1`: 23/23 driver checks PASS. The DNS check was a HARNESS-ERROR at the time; see below.

**Status:** **LOCALLY REPRODUCED** (ledger 26, 27, 28). Ledger 29 is **partial**: session identity and plain-HTTP byte accounting are INTEGRATION-VERIFIED, but HTTPS-tunnel bytes are **not counted**, so ledger 29 is **not met**. **Not SECURITY-TESTED**: the clean-environment rerun and independent review are outstanding.
**Runner:** Claude. **Reviewer:** not assigned.

## Setup

**Image:** `mandate-mitm:wave3` (`sha256:0ac91aba…`) = spike image `sha256:44bc7e00…` + curl 8.14.1 + mitmproxy 12.2.3. `images/mitm/build.sh` refuses to build if the base image ID differs.

**Topology** (`config/compose.yaml`; AM11 static and runtime gate passed before every run):
- `sandbox`: the agent; hardened; shares the netns of `cellside`, the cell owner on AM11 `cellnet_s`.
- `egress`: mitmproxy; the only gateway; on `cellnet_s` and on `edge` (internal).
- `allowed-srv` and `denied-srv`: on `edge`. Each logs every TCP accept, HTTP request and UDP datagram.
- `outside`: on `edge`; positive controls.
- A tcpdump capture runs in `egress`'s network namespace to record every DNS query the proxy makes.

**Policy** (`harness/egress_addon.py`):
- exact hostname allowlist `{allowed-srv}`, lowercased with any trailing dot removed;
- per-session Basic proxy authentication; the session is recorded on every decision;
- 3,000,000-byte per-session budget on HTTP request bodies;
- `connection_strategy=lazy`, `ignore_hosts=.*`: no TLS interception (AM4);
- defence in depth: `server_connect` refuses any non-allowlisted upstream.

## Results (run2; run3 identical verdicts)

Judged at the destination servers' logs and the DNS pcap, not at the proxy's own log.

| ID | Test | Result | Evidence |
|---|---|---|---|
| C-* | Positive controls: `outside` reaches denied-srv directly (logged); allowed-srv is up; UDP to :443 and :9999 is logged | **PASS** (3/3) | server logs |
| T1 / T1b | Allowed HTTP / allowed CONNECT (TLS passthrough) | **PASS** | 200; allowed-srv logged the request from the egress IP; egress logged `sess-1` |
| T2 | CONNECT denied-srv | **PASS** | 403 from the proxy. **denied-srv logged 0 contacts from egress over the whole run** (its only 2 contacts were the `outside` control) |
| T2b–e | CONNECT to denied-srv's IP, allowed-srv's **IP literal**, `allowed-srv.evil.test`, `DENIED-SRV.` | **PASS** (4/4) | all 403; zero contact at either server |
| **No DNS for denied names** | pcap in egress's netns | **PASS** | queries: `allowed-srv` ×16 (**positive control**); `denied-srv`, `evil.test` or any case variant: **0** |
| T3 / T3b | Plain HTTP to denied-srv; `http://allowed-srv@denied-srv/` | **PASS** | 403; zero contact at denied-srv |
| T3c | `Host: denied-srv` header on a request to allowed-srv | **PASS** | the absolute-URL host decides; the connection went only to allowed-srv (200); denied-srv was not contacted |
| T4 | 302 from allowed-srv → denied-srv, `curl -L` | **PASS** | first hop served by allowed-srv; second hop 403; zero contact at denied-srv |
| T5 / T5b | `--noproxy '*'` by name / by IP | **PASS** | cannot resolve / cannot connect; allowed-srv saw nothing from the cell |
| T10 | Raw TCP 80/443 and UDP 443 (QUIC) / 9999 from the cell | **PASS** | `Network is unreachable`; allowed-srv logged **0** datagrams from the cell. UDP is observable, as shown by the control |
| T6a–d | No, bad and unknown-session credentials; CONNECT without credentials | **PASS** (4/4) | 407; allowed-srv not contacted |
| T7 | Byte budget, five 1 MB POSTs | **PASS** | codes 200,200,200,403,403; allowed-srv received **exactly 3** POSTs of 1,000,000 bytes |
| T8 | SSE through the proxy | **PASS** (functional) | 5 events at 0.01 / 0.61 / 1.21 / 1.81 / 2.41 s |
| T9 | Optional TLS-interception mode | **not run** | optional per the playbook |

## Harness error

**run1:** the DNS analysis could not decode queries, because Docker's embedded resolver rewrites the query port. Its positive control (allowed-srv queried) therefore failed, and the "no DNS for denied names" check was **not credited**. Re-analysing the preserved pcap with `tcpdump -T domain` showed 16 `allowed-srv` queries and 0 for denied names. The fix is in `run_s5.sh`; run2 and run3 pass with the fix.

## Limitations

- **Byte budget (G4):** only bodies of plain-HTTP requests seen by the `request` hook are counted. **Bytes inside passthrough CONNECT tunnels (HTTPS) are not counted** with `ignore_hosts=.*`. Counting them needs tunnel byte accounting (e.g. `tcp_message`, or connection-level counters) or TLS interception. **Ledger 29 is met only for plain HTTP.**
- **Allowlist by IP literal:** IP literals are denied even when they point at an allowed host. This is a policy choice, and it is fail-closed.
- **Not tested:** TLS-interception mode (optional T9), and redirect-following logic in non-curl clients (S8).
- The decision is destination-level only; there is no content inspection (AM4).

## Reproduce

```
bash ../images/mitm/build.sh
bash driver/run_s5.sh <label>
```

---

## Addendum (16 Oct): ledger 29, HTTPS-tunnel byte accounting (`harness/egress_addon_v2.py`)

The v1 result and verdict above are unchanged. v1 (`egress_addon.py`) is kept with its evidence.

**Accounting boundary.**
- G4 bounds the bytes the cell sends outward through the egress PEP.
- A non-intercepting proxy (AM4) cannot see HTTPS plaintext. So for CONNECT tunnels the measurable unit is the **client→server bytes the proxy relays**, which are TLS records and include TLS overhead.
- For plain HTTP the unit is the request body.
- Both count against **one per-session budget**. The session of a tunnel is the session authenticated on its CONNECT, mapped by client connection.

**Mechanism.**
- mitmproxy runs tunnels matched by `ignore_hosts` as `TCPLayer(ignore=not show_ignored_hosts)`. With `show_ignored_hosts=true`, a tunnel stays passthrough (no TLS interception) but raises `tcp_message` *before* each chunk is relayed.
- v2 counts each client→server chunk. The chunk that would exceed the budget is emptied and the flow killed.
- The session is then **latched as exhausted**: later CONNECTs and HTTP requests get 403.
- **No different architecture is needed.**

**Runs**

| Run | Configuration | Result | Notes |
|---|---|---|---|
| `20261016T002108-v2-run1` | v2 without `show_ignored_hosts` | T7b/c/d FAIL | **Config error:** `tcp_message` never fired (0 tunnel events). NOTE in run |
| `20261016T002326-v2-run2` | v2 without the exhaustion latch | T7b/c PASS, **T7d FAIL** | Real behaviour: 33 kB of budget remained after the cut, so a small new CONNECT was allowed. The latch was added afterwards (stricter). NOTE in run |
| `20261016T002538-v2-run3` | v2 with latch | T7b/c FAIL | **Observer measurement error:** `srv.py` logged the *declared* Content-Length even for cut reads. Fixed so it logs actual received bytes. NOTE in run |
| **`20261016T002854-v2-run4`** | v2 final | **27/27 PASS** + DNS PASS | — |
| **`20261016T003347-v2-run5`** | v2 final | **27/27 PASS** + DNS PASS | reproduction |
| `20261016T003144-ctl-accounting-off` | **Deliberate control:** v2 with tunnel events off | T7b/c/d FAIL (expected) | The server received **all** bytes (3,500,000 per test), showing the observer detects over-budget tunnel traffic. NOTE in run |

**v2 results (run4 = run5), judged by the server's *received* bytes:**

| ID | Test | Result |
|---|---|---|
| T7 | Plain HTTP, own session: 200,200,200,403,403; exactly 3 complete 1 MB bodies | **PASS** |
| T7b | Five 700 kB HTTPS uploads, budget 3 MB. Codes 200 ×4 then cut. Server received 700,000 ×4 complete **+ 147,301 of the 5th (incomplete)**. Tunnel killed at 2,966,625 counted bytes | **PASS** |
| T7c | Mixed: 2 × 1 MB plain + 1.5 MB HTTPS on one session. HTTPS cut; server received **917,504 of 1,500,000** | **PASS** |
| T7d | New CONNECT after exhaustion → 403; nothing reaches the server | **PASS** |
| T7e | Invariant: counted bytes ≤ 3,000,000 for every session (peaks: sess-p 3,000,000; sess-t 2,966,625; sess-m 2,934,983) | **PASS** |
| T1–T10 (all v1 tests) | Also re-run under v2 | **PASS** |

**Ledger 29:** **INTEGRATION-VERIFIED (local) for the v2 configuration**. Session identity and plain-HTTP plus HTTPS-tunnel byte accounting were observed at the receiving server across the proxy hop. It is **not** SECURITY-TESTED. EG-6 still needs ledger 26–28 SECURITY-TESTED (clean rerun + review).

**Limitations of v2:**
- The budget counts **TLS record bytes**, not plaintext. Delivered application bytes are therefore at most the budget (2,947,301 and 2,917,504 delivered here).
- After a kill, the cut connection is only closed when the client gives up, about 19–20 s here (`flow.kill()` stops relaying immediately, but the server-side socket lingers). That is a resource hold, not a byte leak.
- Server→client bytes are not budgeted.
- Budgets are in-memory per proxy process and reset on restart.
