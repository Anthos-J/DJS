#!/usr/bin/env bash
# S7 run: AM11 static check -> up -> AM11 runtime check (fail closed) -> tests -> evidence -> teardown.
# Usage: bash driver/run_s7.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-${1:-run}"; mkdir -p "$R"; echo "$R" > runs/LATEST
export SPIKE_IMAGE=mandate-spike-py312:wave2
export NGINX_IMAGE=nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
export RUN_DIR="$(cygpath -w "$(pwd)/$R")"
DC="docker compose -f config/compose.yaml"
CHK="python ../S3-isolation/harness/cell_policy.py"
$DC down -v --remove-orphans >/dev/null 2>&1
$CHK static config/compose.yaml --project s7bind > "$R/cell_policy_static.json"; rc=$?
echo "static_check_exit=$rc" | tee "$R/deploy.log"
[ $rc -eq 0 ] || { echo "REFUSED: AM11 static check failed"; exit 3; }
$DC up -d >> "$R/deploy.log" 2>&1; rc=$?; echo "up_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "REFUSED: up failed"; exit 2; }
sleep 5
$CHK runtime s7bind > "$R/cell_policy_runtime.json"; rc=$?; echo "runtime_check_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "TORN DOWN: AM11 runtime check failed"; exit 4; }
{ docker image inspect "$SPIKE_IMAGE" --format 'spike_image={{.Id}}'; echo "nginx_image=$NGINX_IMAGE"; $DC config --images; } > "$R/images.txt"
$DC config > "$R/compose_resolved.yaml"
$DC ps -a --format '{{.Service}} {{.State}} {{.Status}}' > "$R/ps.txt"
for n in $(docker network ls --filter label=com.docker.compose.project=s7bind --format '{{.Name}}'); do docker network inspect "$n" > "$R/net_${n#s7bind_}.json"; done
python driver/s7_driver.py "$R" > "$R/driver_console.log" 2>&1; echo "driver_exit=$?" >> "$R/driver_console.log"
$DC exec -T pep cat /log/pep.jsonl > "$R/pep_log.jsonl"
$DC exec -T backend cat /log/backend_requests.jsonl > "$R/backend_requests.jsonl"
$DC logs --no-color terminator sidecar_a sidecar_b sidecar_c > "$R/nginx_logs.txt" 2>&1
$DC logs --no-color > "$R/compose_logs.txt" 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1    # also discards the per-run test PKI volumes
grep -E "^SUMMARY|driver_exit" "$R/driver_console.log"; grep -E " (FAIL|HARNESS-ERROR) " "$R/driver_console.log"
echo "RUN=$R"
