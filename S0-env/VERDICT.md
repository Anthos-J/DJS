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
