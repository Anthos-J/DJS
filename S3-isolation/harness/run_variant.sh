#!/usr/bin/env bash
# S3 reproducible run: clean teardown -> up -> captures -> probes -> capture analysis.
# Usage: bash harness/run_variant.sh <compose-file-name> <label> [enforce|regression-fixture]
#   enforce (default): deploy through deploy_cells.sh (AM11 static + runtime checks, fail closed).
#   regression-fixture: deploy WITHOUT the gate (only for the non-compliant baseline that must reproduce
#   the T3 failure); the runtime checker still runs and records the violations.
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
CF="$1"; LABEL="$2"; MODE="${3:-enforce}"
N=nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
DC="docker compose -p s3iso -f config/$CF --env-file config/.env"
R="runs/$(date +%Y%m%dT%H%M%S)-$LABEL"; mkdir -p "$R/pcap"; echo "$R" > runs/LATEST
P=$(cygpath -w "$(pwd)/$R/pcap")
{ echo "compose=$CF label=$LABEL mode=$MODE"; docker version --format 'engine={{.Server.Version}}'; date -u; } > "$R/run_meta.txt"
docker rm -f s3cap_host s3cap_cell >/dev/null 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
if [ "$MODE" = enforce ]; then
  bash harness/deploy_cells.sh "$CF" "$R"; rc=$?
  [ $rc -eq 0 ] || { echo "DEPLOY REFUSED/TORN DOWN by AM11 gate (exit $rc); no probes run"; echo "RUN=$R"; exit 3; }
else
  $DC up -d >/dev/null 2>&1 || { echo "UP FAILED"; $DC up -d; exit 2; }
  sleep 3
  python harness/cell_policy.py runtime s3iso > "$R/cell_policy_runtime.json"; echo "runtime_check_exit=$? (regression fixture: non-compliance expected)" > "$R/deploy.log"
fi
sleep 1
$DC ps --format '{{.Service}} {{.State}}' > "$R/ps.txt"
$DC config > "$R/compose_resolved.yaml"
for n in $(docker network ls --filter label=com.docker.compose.project=s3iso --format '{{.Name}}'); do docker network inspect "$n" > "$R/net_${n#s3iso_}.json"; done
docker run --rm --net host $N ip -br addr > "$R/host_vm_interfaces.txt"
docker run -d --name s3cap_host --net host --cap-add NET_RAW --cap-add NET_ADMIN -v "$P:/cap" $N \
  tcpdump -i any -nn -U -s 512 -w /cap/host_vm.pcap 'port 53 or port 111 or port 3128 or port 443 or host 1.1.1.1 or host 8.8.8.8 or icmp or icmp6' >/dev/null
docker run -d --name s3cap_cell --net container:s3iso-sidecar_a-1 --cap-add NET_RAW --cap-add NET_ADMIN -v "$P:/cap" $N \
  tcpdump -i any -nn -U -s 512 -w /cap/cell_a.pcap >/dev/null
sleep 3
S3_COMPOSE="$CF" python harness/run_s3.py "$R" > "$R/probe_console.log" 2>&1
sleep 2
docker stop s3cap_host s3cap_cell >/dev/null; docker rm s3cap_host s3cap_cell >/dev/null
python harness/analyze_pcap.py "$R" > "$R/pcap_analysis.txt" 2>&1
sha256sum "$R"/pcap/*.pcap > "$R/pcap_sha256.txt"
grep SUMMARY "$R/probe_console.log"; grep -E " (FAIL|HARNESS-ERROR) " "$R/probe_console.log"; cat "$R/pcap_analysis.txt"
echo "RUN=$R"
