#!/usr/bin/env bash
# S3 reproducible run: clean teardown -> up -> captures -> probes -> capture analysis.
# Usage: bash harness/run_variant.sh <compose-file-name> <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
CF="$1"; LABEL="$2"
N=nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
DC="docker compose -p s3iso -f config/$CF --env-file config/.env"
R="runs/$(date +%Y%m%dT%H%M%S)-$LABEL"; mkdir -p "$R/pcap"; echo "$R" > runs/LATEST
P=$(cygpath -w "$(pwd)/$R/pcap")
{ echo "compose=$CF label=$LABEL"; docker version --format 'engine={{.Server.Version}}'; date -u; } > "$R/run_meta.txt"
docker rm -f s3cap_host s3cap_cell >/dev/null 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
$DC up -d >/dev/null 2>&1 || { echo "UP FAILED"; $DC up -d; exit 2; }
sleep 4
$DC ps --format '{{.Service}} {{.State}}' > "$R/ps.txt"
$DC config > "$R/compose_resolved.yaml"
for n in cellnet_a cellnet_b edge; do docker network inspect "s3iso_$n" > "$R/net_$n.json"; done
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
