#!/usr/bin/env bash
# S2 in the pinned python:3.12 spike image, with no network. Usage: bash harness/run_container.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
IMG=mandate-spike-py312:wave2
R="runs/$(date +%Y%m%dT%H%M%S)-container-${1:-run}"; mkdir -p "$R"
W=$(cygpath -w "$(pwd)")
D=(docker run --rm --network none -e PYTHONIOENCODING=utf-8 -v "$W:/s2" -w /s2 "$IMG")
docker image inspect $IMG --format 'image_id={{.Id}}' > "$R/image.txt"
"${D[@]}" sh -c 'python -V; cedar --version; cvc5 --version | head -1; cat /opt/tools/tools_manifest.json; pip freeze' > "$R/versions.txt" 2>&1
sha256sum config/* > "$R/config_sha256.txt"
"${D[@]}" python harness/s2_cedarpy.py "$R/cedarpy" > "$R/cedarpy.log" 2>&1; echo "exit=$?" >> "$R/cedarpy.log"
"${D[@]}" python harness/s2_symcc.py "$R/symcc" > "$R/symcc.log" 2>&1; echo "exit=$?" >> "$R/symcc.log"
"${D[@]}" python harness/s2_differential.py cedar "$R/differential" 0 > "$R/differential.log" 2>&1; echo "exit=$?" >> "$R/differential.log"
grep -h -E '^SUMMARY|^exit=' "$R"/*.log; grep -o '"verdict": "[A-Z]*"' "$R/differential/results.jsonl"; grep -o '"samples": [0-9]*, "mismatches": [0-9]*' "$R/differential/results.jsonl"
echo "RUN=$R"
