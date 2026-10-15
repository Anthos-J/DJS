#!/usr/bin/env bash
# Fail-closed deployment of a MANDATE cell topology (AM11).
#   1. static policy check of the resolved Compose model  -> refuse to deploy on violation
#   2. docker compose up -d
#   3. runtime policy check of the effective network/container state -> tear down on violation
# Usage: bash harness/deploy_cells.sh <compose-file-name> [<evidence-dir>]
# Exit: 0 deployed and compliant; 3 refused (static); 4 deployed, non-compliant, torn down; 2 checker or up error (torn down).
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
CF="$1"; OUT="${2:-$(mktemp -d)}"; mkdir -p "$OUT"
DC="docker compose -p s3iso -f config/$CF --env-file config/.env"

python harness/cell_policy.py static "config/$CF" --env-file config/.env --project s3iso > "$OUT/cell_policy_static.json"
rc=$?; echo "static_check_exit=$rc" | tee -a "$OUT/deploy.log"
if [ $rc -ne 0 ]; then echo "REFUSED: static AM11 policy check failed (exit $rc); nothing deployed" | tee -a "$OUT/deploy.log"; exit 3; fi

$DC up -d >> "$OUT/deploy.log" 2>&1
rc=$?; echo "up_exit=$rc" | tee -a "$OUT/deploy.log"
if [ $rc -ne 0 ]; then $DC down -v --remove-orphans >/dev/null 2>&1; echo "REFUSED: compose up failed; torn down" | tee -a "$OUT/deploy.log"; exit 2; fi
sleep 3

python harness/cell_policy.py runtime s3iso > "$OUT/cell_policy_runtime.json"
rc=$?; echo "runtime_check_exit=$rc" | tee -a "$OUT/deploy.log"
if [ $rc -ne 0 ]; then
  $DC down -v --remove-orphans >/dev/null 2>&1
  echo "TORN DOWN: effective state violates AM11 (exit $rc)" | tee -a "$OUT/deploy.log"; [ $rc -eq 3 ] && exit 4 || exit 2
fi
echo "DEPLOYED: static and runtime AM11 checks passed" | tee -a "$OUT/deploy.log"
