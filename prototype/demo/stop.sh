#!/usr/bin/env bash
# Stop the MANDATE demo: console process, then the prototype's containers and its own Docker volumes (demo state only).
set -u
cd "$(dirname "$0")/.."
for d in "/c/Program Files/Docker/Docker/resources/bin" "/c/Users/$USERNAME/AppData/Local/Programs/DockerDesktop/resources/bin"; do
  [ -d "$d" ] && export PATH="$d:$PATH"
done
export MSYS_NO_PATHCONV=1 SPIKE_IMAGE=mandate-spike-py312:wave2 NGINX_IMAGE=x RUN_DIR=x
if [ -f demo/.console.pid ]; then kill "$(cat demo/.console.pid)" 2>/dev/null && echo "console stopped"; rm -f demo/.console.pid; fi
docker compose -f compose.yaml down -v --remove-orphans >/dev/null 2>&1 && echo "prototype containers and demo volumes removed"
