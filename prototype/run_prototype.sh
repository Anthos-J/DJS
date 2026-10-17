#!/usr/bin/env bash
# MANDATE prototype: AM11 static gate -> up -> AM11 runtime gate (fail closed) -> optional e2e -> leaves the demo running.
# Usage: bash run_prototype.sh [e2e]      UI: http://127.0.0.1:8800 (owner token: demo-owner-token unless MANDATE_OWNER_TOKEN set)
# Stop:  docker compose -f compose.yaml down -v
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")"
command -v cygpath >/dev/null || export PATH="$(pwd)/../tools:$PATH"
R="e2e/runs/$(date +%Y%m%dT%H%M%S)-${1:-demo}"; mkdir -p "$R"
export SPIKE_IMAGE=mandate-spike-py312:wave2
if [ "${MANDATE_ENGINE:-}" = "E4.3" ]; then   # E4.3's injection detector needs onnxruntime in the control plane only
  export CONTROL_IMAGE=mandate-control-e43:1
  docker image inspect "$CONTROL_IMAGE" >/dev/null 2>&1 || docker build -q -t "$CONTROL_IMAGE" control/image >/dev/null
  [ -f config/injection_model/model.onnx ] || echo "NOTE: config/injection_model/model.onnx missing; E4.3 runs without the injection detector"
fi
export NGINX_IMAGE=nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
export RUN_DIR="$(cygpath -w "$(pwd)/$R")"
DC="docker compose -f compose.yaml"; CHK="python ../S3-isolation/harness/cell_policy.py"
$DC down -v --remove-orphans >/dev/null 2>&1
$CHK static compose.yaml --project mandate > "$R/cell_policy_static.json"; rc=$?; echo "static_check_exit=$rc" | tee "$R/deploy.log"
[ $rc -eq 0 ] || { echo "REFUSED: AM11 static check failed"; exit 3; }
$DC up -d >> "$R/deploy.log" 2>&1; rc=$?; echo "up_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; exit 2; }
sleep 6
$CHK runtime mandate > "$R/cell_policy_runtime.json"; rc=$?; echo "runtime_check_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "TORN DOWN: AM11 runtime check failed"; exit 4; }
{ docker image inspect "$SPIKE_IMAGE" --format 'spike_image={{.Id}}'; echo "nginx_image=$NGINX_IMAGE"; [ -n "${CONTROL_IMAGE:-}" ] && docker image inspect "$CONTROL_IMAGE" --format 'control_image={{.Id}}'; } > "$R/images.txt"
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8800/api/meta >/dev/null 2>&1 && break; sleep 1; done
if [ "${1:-}" = "demo" ]; then
  MANDATE_DEMO=1 python e2e/e2e_driver.py "$R" > "$R/e2e_console.log" 2>&1; grep -E "SUMMARY" "$R/e2e_console.log"
fi
if [ "${1:-}" = "e2e" ]; then
  python e2e/e2e_driver.py "$R" > "$R/e2e_console.log" 2>&1; echo "e2e_exit=$?" >> "$R/e2e_console.log"
  $DC exec -T backend cat /log/effects.jsonl > "$R/tool_effects.jsonl"; $DC exec -T pep cat /log/pep.jsonl > "$R/pep_log.jsonl"
  $DC exec -T control cat /data/audit.jsonl > "$R/control_audit.jsonl"
  grep -E "PASS|FAIL|SUMMARY" "$R/e2e_console.log"
fi
echo "RUN=$R"; echo "Dashboard: http://127.0.0.1:8800  (stop: docker compose -f compose.yaml down -v)"
