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
