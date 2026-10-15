#!/usr/bin/env bash
# S8 run: AM11 static gate -> up -> AM11 runtime gate -> tests -> evidence -> teardown. Usage: bash driver/run_s8.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-${1:-run}"; mkdir -p "$R"; echo "$R" > runs/LATEST
export RUN_DIR="$(cygpath -w "$(pwd)/$R")"
export MITM_IMAGE=mandate-mitm:wave3 SPIKE_IMAGE=mandate-spike-py312:wave2 NGINX_IMAGE=nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
export NETSHOOT_IMAGE=nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
DC="docker compose -f config/compose.yaml"; CHK="python ../S3-isolation/harness/cell_policy.py"
$DC down -v --remove-orphans >/dev/null 2>&1
$CHK static config/compose.yaml --project s8e2e > "$R/cell_policy_static.json"; rc=$?; echo "static_check_exit=$rc" | tee "$R/deploy.log"
[ $rc -eq 0 ] || { echo "REFUSED: AM11 static check failed"; exit 3; }
$DC up -d >> "$R/deploy.log" 2>&1; rc=$?; echo "up_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; exit 2; }
sleep 6
$CHK runtime s8e2e > "$R/cell_policy_runtime.json"; rc=$?; echo "runtime_check_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "TORN DOWN: AM11 runtime check failed"; exit 4; }
{ docker image inspect "$MITM_IMAGE" --format 'mitm_image={{.Id}}'; echo "netshoot=$NETSHOOT_IMAGE"; } > "$R/images.txt"
$DC config > "$R/compose_resolved.yaml"
for n in $(docker network ls --filter label=com.docker.compose.project=s8e2e --format '{{.Name}}'); do docker network inspect "$n" > "$R/net_${n#s8e2e_}.json"; done
python driver/s8_driver.py "$R" > "$R/driver_console.log" 2>&1; echo "driver_exit=$?" >> "$R/driver_console.log"
for s in "pep /log/pep.jsonl" "backend /log/effects.jsonl" "backend /log/backend_requests.jsonl" "egress /log/egress.jsonl" "allowed-srv /log/allowed-srv.jsonl" "allowed-srv /log/denied-srv.jsonl" "model-proxy /log/model_proxy.jsonl" "mock-provider /log/provider.jsonl"; do set -- $s; $DC exec -T $1 cat $2 > "$R/$1__$(basename $2)"; done
$DC logs --no-color > "$R/compose_logs.txt" 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
grep -E "^SUMMARY|driver_exit" "$R/driver_console.log"; grep -E " (FAIL|HARNESS-ERROR) " "$R/driver_console.log"
echo "RUN=$R"
