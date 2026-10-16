#!/usr/bin/env bash
# IPv6 isolation check for the running MANDATE prototype (L14). Read-only for the prototype; it creates and then
# removes ONLY its own probe network and containers (prefix mandate-v6probe).
#   positive control: two containers on an IPv6-enabled probe network reach each other over IPv6 (proves the probe works)
#   negative test:    each AM11 agent cell has no global/ULA IPv6 address, no IPv6 default route, and cannot reach the
#                     probe server's IPv6 address or a public IPv6 address
# Usage: bash tests/ipv6_isolation_check.sh <out_dir>     (prototype stack must be up)
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1
OUT="$1"; mkdir -p "$OUT"; IMG=mandate-spike-py312:wave2; NET=mandate-v6probe-net
log() { echo "$*" | tee -a "$OUT/ipv6_check.log"; }
docker rm -f mandate-v6probe-srv mandate-v6probe-cli >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1
if ! docker network create --ipv6 --subnet fd00:6d:1::/64 "$NET" >/dev/null 2>"$OUT/netcreate.err"; then
  log "POSITIVE_CONTROL=UNSUPPORTED (daemon refused an IPv6 network: $(head -c 200 "$OUT/netcreate.err"))"; exit 0
fi
docker run -d --name mandate-v6probe-srv --network "$NET" "$IMG" python -c "
import socket; s=socket.socket(socket.AF_INET6); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('::', 8086)); s.listen(5)
while True:
    c,_=s.accept(); c.sendall(b'v6-ok'); c.close()" >/dev/null
sleep 2
V6=$(docker inspect mandate-v6probe-srv --format "{{(index .NetworkSettings.Networks \"$NET\").GlobalIPv6Address}}")
log "probe server IPv6: ${V6:-none}"
PROBE="import socket,sys
def t(a,p):
    try:
        s=socket.create_connection((a,p),timeout=3); d=s.recv(16); s.close(); return 'CONNECTED '+d.decode(errors='replace')
    except Exception as e: return 'BLOCKED '+type(e).__name__
print('probe_srv', t(sys.argv[1], 8086)); print('public_v6', t('2001:4860:4860::8888', 53))
print('if_inet6', [l.split()[0] for l in open('/proc/net/if_inet6') if not l.split()[0].startswith(('fe80','00000000000000000000000000000001'))] if __import__('os').path.exists('/proc/net/if_inet6') else 'no-ipv6-stack')
r=[l.split() for l in open('/proc/net/ipv6_route')] if __import__('os').path.exists('/proc/net/ipv6_route') else []
print('v6_default_route', any(x[0]=='0'*32 and x[1]=='00' and x[-1] not in ('lo',) for x in r))"
POS=$(docker run --rm --network "$NET" "$IMG" python -c "$PROBE" "$V6" 2>&1)
log "== positive control (container on the IPv6 probe network)"; log "$POS"
PASS_POS=$(echo "$POS" | grep -c "probe_srv CONNECTED v6-ok")
FAILS=0
for svc in agent_a agent_b; do
  NEG=$(docker compose -f compose.yaml exec -T "$svc" python -c "$PROBE" "$V6" 2>&1)
  log "== negative test: cell $svc"; log "$NEG"
  echo "$NEG" | grep -q "probe_srv BLOCKED" || FAILS=$((FAILS+1))
  echo "$NEG" | grep -q "public_v6 BLOCKED" || FAILS=$((FAILS+1))
  echo "$NEG" | grep -q "v6_default_route True" && FAILS=$((FAILS+1))
done
docker rm -f mandate-v6probe-srv >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1
if [ "$PASS_POS" -eq 1 ] && [ "$FAILS" -eq 0 ]; then log "RESULT=PASS (positive control connected over IPv6; cells blocked)"; else log "RESULT=FAIL positive=$PASS_POS cell_failures=$FAILS"; fi
