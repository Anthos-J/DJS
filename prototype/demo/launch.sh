#!/usr/bin/env bash
# MANDATE judge demo: one-command start (Windows 11 + Docker Desktop + Git Bash).
#   bash demo/launch.sh        -> preflight -> deploy with AM11 gates (engine E4.2.1, explicitly) -> verify engine -> seed -> console
#   bash demo/stop.sh          -> stop the console and remove the demo containers and volumes
# Console: http://127.0.0.1:8090   (control-plane API: http://127.0.0.1:8800)
set -u
cd "$(dirname "$0")/.."                                    # validation/prototype
for d in "/c/Program Files/Docker/Docker/resources/bin" "/c/Users/$USERNAME/AppData/Local/Programs/DockerDesktop/resources/bin"; do
  [ -d "$d" ] && export PATH="$d:$PATH"
done
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
export MANDATE_ENGINE=E4.2.1 MANDATE_RECOVERY=0 MANDATE_CONSOLE_DEMO_TOKEN=1   # submission engine is explicit, never the default (E2)
export SPIKE_IMAGE=mandate-spike-py312:wave2
export NGINX_IMAGE=nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
PY=python; command -v python >/dev/null 2>&1 || PY=python3
export MANDATE_BASH="$(cygpath -m "$(command -v bash)" 2>/dev/null || command -v bash)"   # console reset uses this Git Bash
fail() { echo "PREFLIGHT FAILED: $*"; echo "See README_JUDGES.md -> Troubleshooting."; exit 1; }

echo "== MANDATE demo launcher (engine $MANDATE_ENGINE)"
echo "-- preflight"
command -v docker >/dev/null 2>&1 || fail "docker CLI not found (install/start Docker Desktop)"
docker info >/dev/null 2>&1 || fail "Docker daemon not reachable (start Docker Desktop and wait until it is running)"
command -v "$PY" >/dev/null 2>&1 || fail "Python 3 not found on PATH"
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || fail "Python >= 3.10 required on the host"
docker image inspect "$SPIKE_IMAGE" >/dev/null 2>&1 || fail "image $SPIKE_IMAGE missing (build: see README_JUDGES.md, 'Building the image')"
docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1 || { echo "   pulling pinned nginx image"; docker pull "$NGINX_IMAGE" >/dev/null || fail "cannot pull $NGINX_IMAGE"; }
if [ -f demo/.console.pid ] && kill -0 "$(cat demo/.console.pid)" 2>/dev/null; then kill "$(cat demo/.console.pid)" 2>/dev/null; sleep 1; fi
"$PY" - <<'PYEOF' || fail "port 8090 or 8800 is in use by another program"
import socket
for p in (8090,):
    s = socket.socket(); s.settimeout(0.5)
    if s.connect_ex(("127.0.0.1", p)) == 0: raise SystemExit(1)
PYEOF
echo "   ok: docker, python, images, ports"

echo "-- deploy (AM11 static gate -> up -> AM11 runtime gate; fail closed)"
out=$(bash run_prototype.sh console 2>&1); rc=$?
echo "$out" | grep -E "exit|REFUSED|TORN|RUN=" | sed 's/^/   /'
[ $rc -eq 0 ] || fail "deployment refused (exit $rc); the AM11 gates or docker compose failed"
echo "$out" | grep -q "runtime_check_exit=0" || fail "AM11 runtime gate did not pass"

echo "-- verify engine and readiness"
for i in $(seq 1 40); do curl -sf http://127.0.0.1:8800/api/meta -o demo/.meta.json 2>/dev/null && break; sleep 1; done
[ -s demo/.meta.json ] || fail "control plane did not become ready (docker compose -f compose.yaml logs control)"
eng=$("$PY" -c "import json; print(json.load(open('demo/.meta.json'))['engine'])")
[ "$eng" = "E4.2.1" ] || fail "control plane reports engine '$eng', expected E4.2.1"
echo "   control plane ready, engine $eng"
"$PY" console/console.py --seed | sed 's/^/   /' || fail "seeding the demo baseline failed"

echo "-- console"
nohup "$PY" console/console.py > demo/console.log 2>&1 &
echo $! > demo/.console.pid
for i in $(seq 1 20); do curl -sf http://127.0.0.1:8090/console/health >/dev/null 2>&1 && break; sleep 1; done
curl -sf http://127.0.0.1:8090/console/health >/dev/null 2>&1 || fail "console did not start (see demo/console.log)"
echo
echo "READY  ->  open http://127.0.0.1:8090"
echo "Stop   ->  bash demo/stop.sh"
