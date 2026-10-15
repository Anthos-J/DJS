#!/usr/bin/env bash
# S4a v2 run (baseline + candidate) in the pinned AgentDojo image, no network. Usage: bash harness/run_s4a.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-${1:-run}"; mkdir -p "$R"
IMG=mandate-agentdojo:wave5
docker image inspect $IMG --format 'image_id={{.Id}}' > "$R/image.txt"
sha256sum config/tool_annotations.json config/v2/* ../S2-cedar/config/policies_P.cedar ../S2-cedar/config/schema.cedarschema > "$R/inputs_sha256.txt"
docker run --rm --network none -e PYTHONIOENCODING=utf-8 \
  -v "$(cygpath -w "$(pwd)/config"):/cfg:ro" -v "$(cygpath -w "$(pwd)/../S2-cedar/config"):/s2cfg:ro" \
  -v "$(cygpath -w "$(pwd)/harness"):/h:ro" -v "$(cygpath -w "$(pwd)/$R"):/out" \
  $IMG python /h/s4a_replay_v2.py /out > "$R/console.log" 2>&1; echo "exit=$?" >> "$R/console.log"
tail -40 "$R/console.log"; echo "RUN=$R"
