# S0 Environment baseline — PASS (run: runs/20261015T191347)

| Check | Result | Evidence |
|---|---|---|
| Docker context | desktop-linux (npipe dockerDesktopLinuxEngine) | session log |
| Engine / client | 29.8.2 / 29.8.2, linux/amd64, kernel 6.6.87.2-microsoft-standard-WSL2, cgroup v2 | runs/20261015T191347/docker_info.json |
| Engine >= 26.0.0 (CVE-2024-29018 fixed) | yes (29.8.2) | docker_info.json |
| Compose | v5.6.0 | runs/20261015T191347/compose_version.txt |
| Runtime check (hello-world; NOT a security test) | ran, printed "Hello from Docker!" | runs/20261015T191347/hello.log |
| Images pinned by digest | python:3.12-slim@sha256:a6e34c59…; nicolaka/netshoot@sha256:b09d9b21… | runs/20261015T191347/images.txt |
| Probe tools present in netshoot | dig curl nc tcpdump ip getent ping | runs/20261015T191347/netshoot_tools.txt |
| Disk free | ~18 GB on C: | runs/20261015T191347/disk.txt |
| Notes | Docker CLI is a per-user install (C:\Users\SEBIN\AppData\Local\Programs\DockerDesktop\resources\bin) and was not on this shell's PATH; added explicitly. Engine HTTP(S) proxy = http.docker.internal:3128 (Desktop internal); not injected into containers — probed as a bypass path in S3. | |

## Recheck: 15 Oct 2026, 20:39 local. PASS (run: runs/20261015T203952-recheck)

| Check | Result | Evidence |
|---|---|---|
| Context / engine / client | desktop-linux; 29.8.2 / 29.8.2 linux/amd64; kernel 6.6.87.2-microsoft-standard-WSL2; engine ID 8264e8e1-a439-48c3-a7cf-3ebd405ade2d | runs/20261015T203952-recheck/versions.txt |
| Compose | v5.6.0 | versions.txt |
| Runtime check (hello-world; NOT a security test) | "Hello from Docker!", exit 0. Agrees with the user-reported run. | hello.log |
| Image digests = pins in S3 `config/.env` | yes, unchanged since run 20261015T191347 | images.txt |
| Probe tools | dig curl nc tcpdump ip getent socat present | tools.txt |
| Disk free | 17 GB on C: (97% used). Enough for S3. **Low for the full stack.** | disk.txt |
| Repo state before the run | git clean, HEAD 1b90240; 0 containers; only the default networks | session log |

**Freshness caveat:** images pulled during the earlier runs (python:3.12-slim, netshoot, hello-world) are still present, so this engine was **not** freshly reset since S3 last ran. The engine ID was not recorded before, so it cannot be compared. These runs are therefore **same-machine reruns**, not the playbook's "clean-environment rerun".
