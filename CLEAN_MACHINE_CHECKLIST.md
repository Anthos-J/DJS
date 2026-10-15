# Clean-machine verification checklist: S3, S1, S7, S5 v2, S6

**Purpose:** the playbook's SECURITY-TESTED level (§3.1) requires a **clean-environment rerun** and rule 7 requires an **independent reviewer**. This checklist is for a person *other than the runner* on a *second machine*.

**State:** **NOT EXECUTED.** None of these gates has passed until this checklist has been run on a second machine and the sign-off table at the end is completed by a human.

Source commit for the rerun: the commit that contains this file. Record the hash in the sign-off.

## 0. Machine prerequisites (record every value)

| Item | Requirement | Why |
|---|---|---|
| Machine | A different physical or virtual machine; Docker freshly installed or reset (no images from the original runs) | "Clean environment" |
| Platform | **Preferred:** Windows 11 + Docker Desktop 4.95.0 / Engine 29.8.2 (WSL2), the same as the original, to *reproduce*. **Alternative:** Linux + Docker Engine ≥ 29: this produces **new platform-specific evidence**, not a reproduction. S3 behaviour (gateway mode, host-namespace services) is platform-specific | S3 claims are per platform |
| Shell | Git Bash (Windows) or bash (Linux). On Linux: `export PATH="$PWD/validation/tools:$PATH"` (the `cygpath` shim) | Run scripts call `cygpath -w` |
| Host Python | ≥ 3.10 on PATH as `python`, standard library only | Drivers and `cell_policy.py` run on the host |
| Network | Internet for image builds and pulls only. Tests are local; no test contacts the internet or a real metadata/provider endpoint | — |
| Disk | ≥ 15 GB free | Images and pcaps |

Record: `docker version`, `docker info`, `docker compose version`, `python -V`, OS version, free disk. Put them in `validation/CLEAN_RERUN/<date>/env.txt`.

## 1. Fetch, verify and build

```bash
git clone <repo> && cd <repo>/validation && git checkout <commit>
```
```bash
git log --oneline -1
```
```bash
git tag -v s3-am11-local-repro || git show s3-am11-local-repro --stat | head -5
```
```bash
docker pull nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
```
```bash
docker pull python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
```
```bash
docker pull nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
```
```bash
docker build -t mandate-spike-py312:wave2 images/spike-py312 > CLEAN_RERUN_build_spike.log 2>&1
```

**Expected:** the build succeeds. The Cedar CLI hash check passes (`deb3a834…`, published). The cvc5 hash check passes (`1a1cda20…`). **The cvc5 pin is trust-on-first-use, not a published hash: the reviewer should decide whether to independently obtain and compare the cvc5 1.3.1 Linux static zip.**

Then the mitmproxy image. `build.sh` checks the spike image ID. **On a new machine the ID will differ**, because image IDs are build-specific, so it will refuse to build. Record the new ID and build directly:
```bash
docker build -t mandate-mitm:wave3 images/mitm
```
**Expected:** mitmproxy 12.2.3, Python 3.12.15. Record both image IDs.

## 2. Spikes, in this order

Run each command from `validation/<spike>/`. Record the exit code and the run directory it prints (`RUN=…`). **Do not edit harness files.** If anything fails, record it as found; do not retry silently.

| # | Spike | Command | Expected result | Evidence produced (in the printed run dir) |
|---|---|---|---|---|
| 1 | S3 regression + canonical | `bash harness/regression.sh` | `REGRESSION: 0 failing assertion(s)`. R1 24/24 mutations; R2 typo and no-isolated refused (exit 3, 0 containers); **R3: the original topology still FAILS T3**, with T3e/T3f/T3g (platform-dependent: on Linux Engine this may differ, so record the actual result); R4 canonical 0 FAIL / 0 HARNESS-ERROR; R5 drift detected | `runs/*-regression/regression_summary.txt`, `R1-checker/…`, `*-baseline-regression/`, `*-canonical/` (results.jsonl, pcap/, pcap_analysis.json, cell_policy_*.json, host_vm_interfaces.txt, net_*.json) |
| 2 | S1 in containers | `bash harness/run_container.sh clean1` (in `S1-pep/`) | All pass/fail checks PASS: T1–T4, T4-sweep, T6, T7 legacy/auto, T8, T8b-200, T10-rule. Recorded: T5 strip variants (`strip_rc_teloff` removes client keys; `strip_rc` leaks `traceparent`; `strip_msg` strips nothing), T9, T11 | `runs/*-container-clean1/results.jsonl`, backend_requests.jsonl, pep_*.jsonl, writes.log, pip_freeze.txt |
| 3 | S7 credential binding | `bash driver/run_s7.sh clean1` (in `S7-binding/`) | AM11 gate exits 0/0. **38/38 PASS** | `runs/*-clean1/results.jsonl`, pep_log.jsonl, backend_requests.jsonl, nginx_logs.txt, pki_public.json (public data only) |
| 4 | S5 v2 egress | `EGRESS_ADDON=egress_addon_v2.py bash driver/run_s5.sh clean1` (in `S5-egress/`) | AM11 gate 0/0. **27/27 PASS**, `verdict_no_dns_for_denied: PASS`. T7b: server receives 4 × 700,000 complete + 1 incomplete; T7c: 2 × 1,000,000 + 1 incomplete | `runs/*-clean1/results.jsonl`, allowed-srv.jsonl, denied-srv.jsonl (**only `outside` contacts**), egress_log.jsonl, pcap/, dns_analysis.json |
| 4b | S5 control (expected to FAIL) | `EGRESS_ADDON=egress_addon_v2.py FORCE_SHOW_IGNORED_HOSTS=false bash driver/run_s5.sh clean-ctl` | **T7b/T7c/T7d FAIL**, and the server receives 3,500,000 bytes per test. This shows the observer detects leaks | same layout |
| 5 | S6 model route | `bash driver/run_s6.sh clean1` (in `S6-model/`) | AM11 gate 0/0. **33 PASS + 1 BLOCKED (T9)**, including T1e/T1f (Content-Length fix) | `runs/*-clean1/results.jsonl`, provider_log.jsonl (**0 requests with forbidden markers; only the injected key**), model_proxy_log.jsonl |

Optional (not gate-relevant, but useful): S8 `S8_DRIVER=s8_driver_v2.py bash driver/run_s8.sh clean1` should give 27/27, and S4a `bash harness/run_s4a_v2.sh clean1` should give decision hashes `e69d6d61…` (baseline) and `acb29d3e…` (candidate). Both require `images/agentdojo` built.

## 3. What the reviewer must check (independent of the driver summaries)

For each run directory:
1. Open the raw observer logs, not just `SUMMARY`:
   - S3: pcaps / `pcap_analysis.json`; `host_vm_interfaces.txt` shows no IPv4 on the cell bridges.
   - S7: `backend_requests.jsonl` has no JWT, Authorization or client cert.
   - S5: `denied-srv.jsonl` has no contacts from the egress IP; the DNS analysis shows the positive control.
   - S6: `provider_log.jsonl`.
2. Confirm every negative test's paired positive control passed (`control` field in `results.jsonl`). **A negative without a passing control is a HARNESS-ERROR, not a PASS.**
3. Confirm the AM11 gate ran first: `deploy.log` shows `static_check_exit=0`, `up_exit=0`, `runtime_check_exit=0`.
4. Compare with the original evidence (`STATUS.md`, each `VERDICT.md`). Note every difference.
5. Spot-check at least one harness file per spike against what the VERDICT claims it does.

## 4. Known limitations the reviewer should keep in view (do not need fixing to sign)

- cvc5 is pinned trust-on-first-use.
- `_meta` stripping depends on `FASTMCP_TELEMETRY_MODE=off` (AM12 not adopted).
- Sidecar compromise is an accepted residual risk and is untested.
- **There is no IPv6 bypass test**; the evidence is that the profile disables IPv6 and there is no IPv6 path.
- Drift detection is deploy-time or on-demand only.
- S5 v2 counts TLS-record bytes; cut connections linger about 20 s; outbound bytes only.
- S6 uses a mock provider only.
- The mitmproxy image breaks the FastMCP client (dependency conflict).

## 5. Sign-off (to be completed by humans; leave blank until done)

| Spike | Rerun by (name) | Machine / platform | Date | Commit | Result matches expected? | Reviewer (name, ≠ runner) | Reviewer verdict | Notes |
|---|---|---|---|---|---|---|---|---|
| S3 | | | | | | | | |
| S1 | | | | | | | | |
| S7 | | | | | | | | |
| S5 v2 | | | | | | | | |
| S6 | | | | | | | | |

Only when a row is complete **and** the reviewer verdict is positive may the corresponding ledger items move to SECURITY-TESTED for **that platform and those versions**:

| Spike | Ledger items |
|---|---|
| S3 | 15–21 |
| S1 | 5, 7 |
| S7 | 23, 24 |
| S5 | 26–28 |
| S6 | 30, 31 |

The gates that then close are EG-2, EG-3, EG-4, EG-6 and EG-7, subject to their other conditions.
