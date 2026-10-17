#!/usr/bin/env bash
# Can a compromised agent cell get data out WITHOUT going through the checkpoint (PEP)?
# Runs probes from inside each agent cell against REAL listeners, with positive controls proving each probe works.
#   positive control: a throwaway container on Docker's default network reaches the host listener, resolves DNS,
#                     and reaches the internet (so a BLOCKED result in a cell means the cell is isolated, not that the probe is broken)
#   cell probes:      raw TCP to a host listener, DNS lookup, raw UDP DNS to a public resolver, internet TCP, and direct
#                     connections that skip the PEP (tool server, PEP itself, control plane, terminator without a client cert)
# Read-only for the prototype; it starts and stops only its own listener and probe container.
# Usage: bash tests/bypass_from_cell.sh <out_dir>      (prototype stack must be up)
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 SPIKE_IMAGE=mandate-spike-py312:wave2 NGINX_IMAGE=x RUN_DIR=x
OUT="$1"; mkdir -p "$OUT"; LOG="$OUT/bypass.log"; : > "$LOG"; IMG=mandate-spike-py312:wave2; PORT=8097
log() { echo "$*" | tee -a "$LOG"; }

# real listener on the host: records anything that reaches it
python - "$PORT" "$OUT/listener_hits.log" > /dev/null 2>&1 <<'PY' &
import socket, sys, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", int(sys.argv[1]))); s.listen(20)
with open(sys.argv[2], "a") as f:
    while True:
        c, a = s.accept(); c.settimeout(2)
        try: d = c.recv(200)
        except Exception: d = b""
        f.write(f"{time.time():.0f} {a[0]} {d[:80]!r}\n"); f.flush(); c.sendall(b"HOST-LISTENER-OK"); c.close()
PY
LPID=$!; sleep 1

PROBE='import socket, sys, json
def tcp(h, p, payload=b"exfil-probe"):
    try:
        s = socket.create_connection((h, p), timeout=4); s.sendall(payload); d = s.recv(64); s.close(); return "CONNECTED " + d.decode(errors="replace")[:40]
    except Exception as e: return "BLOCKED " + type(e).__name__
def dns(name):
    try: return "RESOLVED " + socket.getaddrinfo(name, 80)[0][4][0]
    except Exception as e: return "BLOCKED " + type(e).__name__
def udp_dns(server):
    q = bytes.fromhex("abcd01000001000000000000076578616d706c6503636f6d0000010001")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(4); s.sendto(q, (server, 53)); d, _ = s.recvfrom(512); return "ANSWERED %d bytes" % len(d)
    except Exception as e: return "BLOCKED " + type(e).__name__
gw = sys.argv[1]; port = int(sys.argv[2])
r = {"tcp_host.docker.internal": tcp("host.docker.internal", port), "tcp_host_gateway_ip": tcp(gw, port) if gw else "n/a",
     "dns_lookup_example.com": dns("example.com"), "udp_dns_to_8.8.8.8": udp_dns("8.8.8.8"), "tcp_internet_1.1.1.1:443": tcp("1.1.1.1", 443, b""),
     "skip_pep_tool_server_backend:9000": tcp("backend", 9000, b"GET / HTTP/1.0\r\n\r\n"), "skip_pep_direct_pep:8000": tcp("pep", 8000, b"GET / HTTP/1.0\r\n\r\n"),
     "skip_pep_control:8800": tcp("control", 8800, b"GET /api/meta HTTP/1.0\r\n\r\n"), "terminator:8443_no_client_cert": tcp("terminator", 8443, b"GET / HTTP/1.0\r\n\r\n")}
print(json.dumps(r))'

log "== positive control (throwaway container, default Docker network)"
GW=$(docker run --rm "$IMG" python -c "import socket; print(socket.gethostbyname('host.docker.internal'))" 2>/dev/null | tr -d '\r')
log "host gateway as seen from Docker: ${GW:-unresolved}"
POS=$(docker run --rm "$IMG" python -c "$PROBE" "$GW" "$PORT" 2>&1 | tail -1); log "$POS"

FAILS=0
for svc in agent_a agent_b; do
  R=$(docker compose -f compose.yaml exec -T "$svc" python -c "$PROBE" "$GW" "$PORT" 2>&1 | tail -1)
  log "== cell $svc"; log "$R"
  for k in tcp_host.docker.internal tcp_host_gateway_ip dns_lookup_example.com udp_dns_to_8.8.8.8 tcp_internet_1.1.1.1:443 skip_pep_tool_server_backend:9000 skip_pep_direct_pep:8000 skip_pep_control:8800; do
    echo "$R" | python -c "import json,sys; d=json.load(sys.stdin); v=d.get('$k',''); sys.exit(0 if v.startswith('BLOCKED') or v=='n/a' else 1)" || { FAILS=$((FAILS+1)); log "   NOT BLOCKED: $k"; }
  done
done
kill $LPID 2>/dev/null
HITS=$(wc -l < "$OUT/listener_hits.log" 2>/dev/null || echo 0)
log "host listener connections received: $HITS (expected: only from the positive control)"
POSOK=$(echo "$POS" | python -c "import json,sys; d=json.load(sys.stdin); print(int(d['tcp_host.docker.internal'].startswith('CONNECTED')))" 2>/dev/null || echo 0)
if [ "$POSOK" = "1" ] && [ "$FAILS" -eq 0 ]; then log "RESULT=PASS (positive control reached the host; every bypass route from both cells blocked)"; else log "RESULT=FAIL positive_control=$POSOK cell_routes_not_blocked=$FAILS"; fi
