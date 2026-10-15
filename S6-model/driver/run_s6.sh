#!/usr/bin/env bash
# S6 run: AM11 static gate -> up -> AM11 runtime gate -> tests -> evidence -> teardown. Usage: bash driver/run_s6.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-${1:-run}"; mkdir -p "$R"; echo "$R" > runs/LATEST
export MITM_IMAGE=mandate-mitm:wave3
export NETSHOOT_IMAGE=nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
DC="docker compose -f config/compose.yaml"; CHK="python ../S3-isolation/harness/cell_policy.py"
$DC down -v --remove-orphans >/dev/null 2>&1
$CHK static config/compose.yaml --project s6model > "$R/cell_policy_static.json"; rc=$?; echo "static_check_exit=$rc" | tee "$R/deploy.log"
[ $rc -eq 0 ] || { echo "REFUSED: AM11 static check failed"; exit 3; }
$DC up -d >> "$R/deploy.log" 2>&1; rc=$?; echo "up_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; exit 2; }
sleep 6
$CHK runtime s6model > "$R/cell_policy_runtime.json"; rc=$?; echo "runtime_check_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "TORN DOWN: AM11 runtime check failed"; exit 4; }
{ docker image inspect "$MITM_IMAGE" --format 'mitm_image={{.Id}}'; echo "netshoot=$NETSHOOT_IMAGE"; } > "$R/images.txt"
$DC config > "$R/compose_resolved.yaml"
for n in $(docker network ls --filter label=com.docker.compose.project=s6model --format '{{.Name}}'); do docker network inspect "$n" > "$R/net_${n#s6model_}.json"; done
python driver/s6_driver.py "$R" > "$R/driver_console.log" 2>&1; echo "driver_exit=$?" >> "$R/driver_console.log"
$DC exec -T model-proxy cat /log/model_proxy.jsonl > "$R/model_proxy_log.jsonl"
$DC exec -T mock-provider cat /log/provider.jsonl > "$R/provider_log.jsonl"
$DC logs --no-color > "$R/compose_logs.txt" 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
grep -E "^SUMMARY|driver_exit" "$R/driver_console.log"; grep -E " (FAIL|HARNESS-ERROR) " "$R/driver_console.log"
echo "RUN=$R"
