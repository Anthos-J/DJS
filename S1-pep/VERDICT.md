# S1
See ../STATUS.md (sections *S1 results* for the original Windows host-venv runs, and *Wave 2* for the pinned python:3.12 container runs).
Container runs: `runs/20261015T223758-container-run1` (earlier variant set), `runs/20261015T223900-container-run2`, `runs/20261015T223941-container-run3`.
Host runs (kept separately): `runs/20261015T042540-host-venv`, `runs/20261015T042718-host-venv-rerun`.
Status: ledger 1-4, 8 INTEGRATION-VERIFIED; 5, 7, 9 LOCALLY REPRODUCED. Not SECURITY-TESTED. Reviewer: pending.
Reproduce: `bash harness/run_container.sh <label>`
