#!/usr/bin/env bash
# S1 in pinned python:3.12 containers. Usage: bash harness/run_container.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-container-${1:-run}"; mkdir -p "$R"; echo "$R" > runs/LATEST
export SPIKE_IMAGE=mandate-spike-py312:wave2 RUN_DIR="$(cygpath -w "$(pwd)/$R")"
DC="docker compose -f config/compose.yaml"
$DC down -v --remove-orphans >/dev/null 2>&1
$DC up -d > "$R/up.log" 2>&1 || { echo "UP FAILED"; cat "$R/up.log"; exit 2; }
{ docker image inspect "$SPIKE_IMAGE" --format 'image_id={{.Id}}'; $DC config --images; } > "$R/images.txt"
$DC config > "$R/compose_resolved.yaml"
# wait until backend and every PEP answer on their port
for i in $(seq 1 60); do
  $DC exec -T client python -c "
import socket,sys
for h,p in [('backend',9000)]+[(s,8000) for s in sys.argv[1:]]:
    socket.create_connection((h,p),2).close()" pep_strict pep_default pep_outer pep_inner pep_outer_onrequest pep_inner_onrequest pep_strip_rc pep_strip_msg pep_strip_rc_teloff 2>/dev/null && break
  sleep 1
done
$DC exec -T client sh -c 'python -V; pip freeze' > "$R/pip_freeze.txt"
$DC exec -T client python /harness/client_tests.py /out > "$R/client_console.log" 2>&1; echo "client_tests_exit=$?" >> "$R/client_console.log"
$DC exec -T client sh -c 'cp /data/*.jsonl /data/writes.log /out/ 2>/dev/null; ls /data' > "$R/data_files.txt"
$DC logs --no-color > "$R/compose_logs.txt" 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
grep -E '^SUMMARY|client_tests_exit' "$R/client_console.log"
echo "RUN=$R"
