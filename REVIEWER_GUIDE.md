# MANDATE independent-validation reviewer guide

**For:** a reviewer who did not run the original tests. **Time:** about 1–2 hours of machine time plus review.
**Step-by-step commands:** `CLEAN_MACHINE_CHECKLIST.md`. **Current status of every claim:** `STATUS.md`, Wave 6 section.

## 1. What you are being asked to do

1. **Rerun** S3, S1, S7, S5 v2 and S6 on a machine other than the original. These are the evidence behind entry gates EG-2, EG-3, EG-4, EG-6 and EG-7.
2. **Review** the raw evidence (yours and the original) independently of the drivers' summaries.
3. **Sign off**, or not, in the checklist's §5 table.

Only after both steps may any claim move to SECURITY-TESTED, and only for the platform and versions you used. **Nothing is SECURITY-TESTED today.**

## 2. Prerequisites

| Need | Detail |
|---|---|
| Machine | Not the original laptop. Preferred: Windows 11 + Docker Desktop 4.95.0 / Engine 29.8.2 (true reproduction). A fresh VM is acceptable as a clean *environment* if you judge it so; record it |
| Tools | Docker + Compose v2; bash (Git Bash on Windows); Python ≥ 3.10 as `python`; `sha256sum`; internet for builds and pulls only |
| Shell setup | `export PYTHONDONTWRITEBYTECODE=1`. On Linux also `export PATH="$PWD/tools:$PATH"` from `validation/` (the `cygpath` shim) |
| Disk | ≥ 15 GB free |
| Repo | Clone, then `git checkout <handoff commit>`. Record `git rev-parse HEAD` |

## 3. Commands (from `validation/`)

```bash
python tools/verify_manifest.py
```
```bash
docker build -t mandate-spike-py312:wave2 images/spike-py312
```
```bash
docker build -t mandate-mitm:wave3 images/mitm
```
```bash
cd S3-isolation && bash harness/regression.sh; cd ..
```
```bash
cd S1-pep && bash harness/run_container.sh clean1; cd ..
```
```bash
cd S7-binding && bash driver/run_s7.sh clean1; cd ..
```
```bash
cd S5-egress && EGRESS_ADDON=egress_addon_v2.py bash driver/run_s5.sh clean1; cd ..
```
```bash
cd S5-egress && EGRESS_ADDON=egress_addon_v2.py FORCE_SHOW_IGNORED_HOSTS=false bash driver/run_s5.sh clean-ctl; cd ..
```
```bash
cd S6-model && bash driver/run_s6.sh clean1; cd ..
```

Pull the three pinned base images first; their digests are listed in the checklist §1.

## 4. Expected outcomes

These equal the latest runs on the original machine, which were audited on 16 Oct.

| Step | Expected | Original evidence to compare |
|---|---|---|
| Manifest | `match_at_tag=297 mismatch_at_tag=0`; 3 files changed since the tag | `handoff/manifest_check_original_machine.txt` |
| S3 regression | `REGRESSION: 0 failing assertion(s)`. Includes R3: **the original topology must still FAIL T3** (on Docker Desktop) | `S3-isolation/runs/20261015T230931-regression/` |
| S1 | 12 PASS + 12 RECORDED, 0 FAIL | `S1-pep/runs/20261015T223941-container-run3/` |
| S7 | 38/38 PASS | `S7-binding/runs/20261015T230728-run6/` |
| S5 v2 | 27/27 PASS; `verdict_no_dns_for_denied: PASS` | `S5-egress/runs/20261016T003347-v2-run5/` |
| S5 control | **T7b/T7c/T7d FAIL by design**; the server receives 3,500,000 bytes per test | `S5-egress/runs/20261016T003144-ctl-accounting-off/` |
| S6 | 33 PASS + 1 BLOCKED (T9) | `S6-model/runs/20261016T005849-post-fix-run2/` |

Every run must first show `static_check_exit=0`, `up_exit=0` and `runtime_check_exit=0` in `deploy.log` (the AM11 gate). If a run is refused by the gate, that is a finding, not something to work around.

## 5. What to inspect, beyond the `SUMMARY` lines

- **Positive controls:** in `results.jsonl`, every negative test names its `control`. A negative whose control failed is a HARNESS-ERROR, not a PASS.
- **Independent observers:**

  | Spike | What to check |
  |---|---|
  | S3 | `pcap_analysis.json`; `host_vm_interfaces.txt` (no IPv4 on cell bridges) |
  | S7 | `backend_requests.jsonl` has no JWT, `authorization` or `x-client-cert` |
  | S5 | `denied-srv.jsonl` has **no** contact from the egress IP; `dns_analysis.json` shows the positive-control query |
  | S6 | `provider_log.jsonl` has only the injected key and no forbidden markers |

- **Failed-run records:** the `NOTE*.txt` files in run directories explain every harness error and defect. They are part of the evidence. Check that the explanations are plausible.
- **Spot-check code:** at least one harness file per spike against what its `VERDICT.md` says it does.

## 6. Known platform-specific limitations (record; they do not block sign-off)

- **S3 is platform-specific.** The baseline T3 failure exposes Docker **Desktop** VM host services (rpcbind 111). On Linux Docker Engine, the host-side services and gateway behaviour differ, so R3 may differ. Record the actual result: it is new evidence for that platform, not a reproduction.
- **Scripts were written on Windows.** They prepend the original user's Docker path (harmless elsewhere) and call `cygpath` (shimmed on Linux). The image build scripts' base-ID check refuses on a new machine; build directly as in §3.
- **Transitive Python dependencies** are recorded but not hash-pinned. Compare `pip freeze` outputs.
- **cvc5 1.3.1** is pinned trust-on-first-use (`1a1cda20…`); no published hash exists.
- **The mitmproxy image breaks the FastMCP client** (`typing_extensions` conflict). That is why S8's agent uses the spike image.
- **The evidence manifest** hashed working-copy bytes on Windows. Use `tools/verify_manifest.py` (blob-based), not `sha256sum -c`, on a fresh clone.
- **Design-level residuals (not test failures):**
  - `_meta` stripping needs `FASTMCP_TELEMETRY_MODE=off`;
  - sidecar compromise is an accepted residual risk;
  - no IPv6 bypass test exists (IPv6 is disabled, and there is no IPv6 path);
  - drift detection is deploy-time or on-demand only;
  - S5 v2 counts TLS-record bytes, and cut connections linger about 20 s;
  - S6 uses a mock provider only.

## 7. Out of scope for this review

S4a and S8 (in-process emulation and local integration; their gates EG-8 and EG-9 are already met at their required levels), live-provider tests (BLOCKED pending an owner decision), and the full-stack build (gated on this review).

---
**OA-1 note (16 Oct):** an independent reviewer is no longer a blocker for internal prototype development (`WORKFLOW_AMENDMENT_OA1.md`). The AI self-review in `handoff/AI_SELF_REVIEW.md` is **not** a substitute for this guide's review. Prototype requirement status: `PRB_TRACEABILITY.md`.
