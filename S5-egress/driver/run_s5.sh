#!/usr/bin/env bash
# S5 run: AM11 static gate -> up -> AM11 runtime gate -> DNS capture in egress netns -> tests -> DNS analysis -> evidence -> teardown.
# Usage: bash driver/run_s5.sh <label>
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-${1:-run}"; mkdir -p "$R/pcap"; echo "$R" > runs/LATEST
export MITM_IMAGE=mandate-mitm:wave3
export EGRESS_ADDON="${EGRESS_ADDON:-egress_addon.py}"
# v2 needs TCP events for passthrough tunnels: show_ignored_hosts=true keeps the tunnel un-intercepted but emits tcp_message
if [ "$EGRESS_ADDON" = egress_addon_v2.py ]; then export SHOW_IGNORED_HOSTS=true; else export SHOW_IGNORED_HOSTS=false; fi
[ -n "${FORCE_SHOW_IGNORED_HOSTS:-}" ] && export SHOW_IGNORED_HOSTS=$FORCE_SHOW_IGNORED_HOSTS   # control runs only
echo "egress_addon=$EGRESS_ADDON show_ignored_hosts=$SHOW_IGNORED_HOSTS" > "$R/run_meta.txt"
export NETSHOOT_IMAGE=nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70
DC="docker compose -f config/compose.yaml"; CHK="python ../S3-isolation/harness/cell_policy.py"
docker rm -f s5cap >/dev/null 2>&1; $DC down -v --remove-orphans >/dev/null 2>&1
$CHK static config/compose.yaml --project s5egress > "$R/cell_policy_static.json"; rc=$?; echo "static_check_exit=$rc" | tee "$R/deploy.log"
[ $rc -eq 0 ] || { echo "REFUSED: AM11 static check failed"; exit 3; }
$DC up -d >> "$R/deploy.log" 2>&1; rc=$?; echo "up_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; exit 2; }
sleep 6
$CHK runtime s5egress > "$R/cell_policy_runtime.json"; rc=$?; echo "runtime_check_exit=$rc" | tee -a "$R/deploy.log"
[ $rc -eq 0 ] || { $DC down -v --remove-orphans >/dev/null 2>&1; echo "TORN DOWN: AM11 runtime check failed"; exit 4; }
{ docker image inspect "$MITM_IMAGE" --format 'mitm_image={{.Id}}'; echo "netshoot=$NETSHOOT_IMAGE"; $DC config --images; } > "$R/images.txt"
$DC config > "$R/compose_resolved.yaml"; $DC ps -a --format '{{.Service}} {{.State}}' > "$R/ps.txt"
for n in $(docker network ls --filter label=com.docker.compose.project=s5egress --format '{{.Name}}'); do docker network inspect "$n" > "$R/net_${n#s5egress_}.json"; done
P=$(cygpath -w "$(pwd)/$R/pcap")
docker run -d --name s5cap --net container:s5egress-egress-1 --cap-add NET_RAW --cap-add NET_ADMIN -v "$P:/cap" "$NETSHOOT_IMAGE" \
  tcpdump -i any -nn -U -s 512 -w /cap/egress_dns.pcap 'port 53 or host 127.0.0.11' > /dev/null
sleep 2
python driver/s5_driver.py "$R" > "$R/driver_console.log" 2>&1; echo "driver_exit=$?" >> "$R/driver_console.log"
sleep 1; docker stop s5cap >/dev/null; docker rm s5cap >/dev/null
docker run --rm -v "$P:/cap" "$NETSHOOT_IMAGE" tcpdump -nn -T domain -r /cap/egress_dns.pcap 'udp and host 127.0.0.11' > "$R/pcap/egress_dns.txt" 2>/dev/null
# -T domain: Docker's embedded resolver DNATs queries to a high port, so tcpdump must be told they are DNS
python - "$R" <<'PY' > "$R/dns_analysis.json"
import json, re, sys
txt = open(sys.argv[1] + "/pcap/egress_dns.txt").read()
q = re.findall(r" (?:A|AAAA)\? ([^ ]+?)\.? ", txt)
names = {n: q.count(n) for n in sorted(set(q))}
deny = ["denied-srv", "allowed-srv.evil.test", "DENIED-SRV", "denied-srv."]
out = {"query_counts": names, "positive_control_allowed_srv_queried": names.get("allowed-srv", 0) > 0,
       "denied_names_queried": {n: c for n, c in names.items() if "denied-srv" in n.lower() or "evil.test" in n.lower()},
       "total_lines": len(txt.splitlines())}
out["verdict_no_dns_for_denied"] = "PASS" if out["positive_control_allowed_srv_queried"] and not any(out["denied_names_queried"].values()) else (
    "HARNESS-ERROR" if not out["positive_control_allowed_srv_queried"] else "FAIL")
print(json.dumps(out, indent=1))
PY
sha256sum "$R"/pcap/*.pcap > "$R/pcap_sha256.txt"
$DC exec -T egress cat /log/egress.jsonl > "$R/egress_log.jsonl"
$DC exec -T allowed-srv cat /log/allowed-srv.jsonl > "$R/allowed-srv.jsonl"
$DC exec -T allowed-srv cat /log/denied-srv.jsonl > "$R/denied-srv.jsonl"
$DC logs --no-color > "$R/compose_logs.txt" 2>&1
$DC down -v --remove-orphans >/dev/null 2>&1
grep -E "^SUMMARY|driver_exit" "$R/driver_console.log"; grep -E " (FAIL|HARNESS-ERROR) " "$R/driver_console.log"; grep verdict_no_dns "$R/dns_analysis.json"
echo "RUN=$R"
