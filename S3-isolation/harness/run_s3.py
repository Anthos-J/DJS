"""S3 cell-isolation probe runner (spike harness). Usage: python run_s3.py <run_dir>
Requires the s3iso compose project to be up. Records exact command, exit code, stdout/stderr per probe.
Verdict logic:
  expect=fail    -> PASS if the probe could not reach its target (see `fail_if`), FAIL otherwise
  expect=succeed -> PASS if it reached the target
A negative probe only counts if its paired positive control PASSES (else HARNESS-ERROR)."""
import json, os, re, secrets, subprocess, sys, time
from pathlib import Path

RUN = Path(sys.argv[1]); RUN.mkdir(parents=True, exist_ok=True)
CFG = Path(__file__).resolve().parent.parent / "config"
COMPOSE = os.environ.get("S3_COMPOSE", "compose.yaml")
DC = ["docker", "compose", "-p", "s3iso", "-f", str(CFG / COMPOSE), "--env-file", str(CFG / ".env")]
results = []

def sh(svc, cmd, timeout=90):
    full = DC + ["exec", "-T", svc, "sh", "-c", cmd]
    t0 = time.time()
    try:
        cp = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        rc, out, err = cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = "TIMEOUT", (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "harness timeout"
    return {"svc": svc, "cmd": cmd, "rc": rc, "stdout": out[-2000:], "stderr": err[-2000:], "secs": round(time.time() - t0, 2)}

def probe(pid, svc, cmd, expect, reached, control=None, note=""):
    """reached(r) -> True if the target was reached / action succeeded."""
    r = sh(svc, cmd)
    got = reached(r)
    if expect == "fail":
        verdict = "PASS" if not got else "FAIL"
    elif expect == "succeed":
        verdict = "PASS" if got else "FAIL"
    else:
        verdict = "INFO"
    entry = {"id": pid, "expect": expect, "reached": got, "verdict": verdict, "note": note, **r}
    if control is not None:
        entry["control_id"] = control
        c = next((x for x in results if x["id"] == control), None)
        if c is None or c["verdict"] != "PASS":
            entry["verdict"] = "HARNESS-ERROR" if verdict == "PASS" else verdict
            entry["note"] += " | positive control did not pass, negative result not credited"
    results.append(entry)
    print(f"{pid:28s} {entry['verdict']:14s} rc={r['rc']} {r['stdout'].strip()[:90]!r}", flush=True)
    return entry

rc0 = lambda r: r["rc"] == 0
http_ok = lambda r: r["rc"] == 0 and re.search(r"^[1-5]\d\d$", r["stdout"].strip() or "x") is not None and r["stdout"].strip() != "000"
dig_answer = lambda r: r["rc"] == 0 and "status: NOERROR" in r["stdout"] and "ANSWER: 0" not in r["stdout"]

def ip_of(svc, net):
    cp = subprocess.run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", f"s3iso-{svc}-1"], capture_output=True, text=True)
    nets = json.loads(cp.stdout)
    return nets[f"s3iso_{net}"]["IPAddress"]

def gw_of(net):
    cp = subprocess.run(["docker", "network", "inspect", "-f", "{{json .IPAM.Config}}", f"s3iso_{net}"], capture_output=True, text=True)
    cfg = json.loads(cp.stdout)
    return cfg[0].get("Gateway", "")

ctx = {"cellnet_a_gateway_ip": gw_of("cellnet_a"), "sidecar_b_ip": ip_of("sidecar_b", "cellnet_b"),
       "outside_ip": ip_of("outside", "edge"), "mdfixture_ip": ip_of("mdfixture", "edge"),
       "neighbour_a2_ip": ip_of("neighbour_a2", "cellnet_a")}
tok = secrets.token_hex(4)
ctx["dns_probe_cell"] = f"s3probe-{tok}-cell.example.com"
ctx["dns_probe_ctl"] = f"s3probe-{tok}-ctl.example.com"
(RUN / "context.json").write_text(json.dumps(ctx, indent=1)); print("context:", ctx)

# ---------------- positive controls first ----------------
probe("C-T1a-outside-https", "outside", "curl -sS -m 8 -o /dev/null -w '%{http_code}' https://example.com", "succeed", http_ok)
probe("C-T1b-outside-tcp1111", "outside", "nc -zv -w 4 1.1.1.1 443", "succeed", rc0)
probe("C-T2a-outside-dig", "outside", f"dig +time=3 +tries=1 {ctx['dns_probe_ctl']}", "succeed",
      lambda r: r["rc"] == 0 and ("status: NXDOMAIN" in r["stdout"] or "status: NOERROR" in r["stdout"]),
      note="positive control: upstream answers (NXDOMAIN for a nonexistent example.com subdomain counts as an upstream answer)")
probe("C-T2b-outside-dig-direct", "outside", "dig +time=3 +tries=1 @1.1.1.1 example.com", "succeed", dig_answer)
probe("C-T3-outside-host-docker-internal", "outside", "getent hosts host.docker.internal", "succeed", rc0)
probe("C-T3-outside-proxy3128", "outside", "nc -zv -w 3 http.docker.internal 3128", "INFO", rc0,
      note="does a normal container reach Desktop's internal proxy? informational")
probe("C-T5-outside-gateway", "outside", "curl -sS -m 5 http://gateway:8080/echo", "succeed", lambda r: "gateway-ok" in r["stdout"])
probe("C-T6-sidecar-reads-secret", "sidecar_a", "cat /secrets/cell.key", "succeed", lambda r: "DUMMY-CELL-KEY" in r["stdout"])
probe("C-T7a-privctl-iplink", "privctl_a", "ip link set lo mtu 65536", "succeed", rc0)
probe("C-T7b-privctl-tcpdump", "privctl_a", "timeout 4 tcpdump -i any -c 1 -w /dev/null 2>&1; test $? -ne 1", "succeed", rc0,
      note="tcpdump can open a capture socket (exit 124 timeout or 0 = opened; 1 = permission error)")
probe("C-T8-outside-mdfixture", "outside", "curl -sS -m 5 http://mdfixture/latest/meta-data/token", "succeed", lambda r: "FAKE-NOT-A-SECRET" in r["stdout"])
probe("C-T9-own-sidecar-loopback", "agent_a", "nc -w 3 127.0.0.1 8081 </dev/null", "succeed", lambda r: "sidecar_a_loopback" in r["stdout"],
      note="intended path: agent reaches its own sidecar on loopback")
probe("C-T9-crosscell-ctl", "gateway", f"python -c \"import socket;s=socket.create_connection(('{ctx['sidecar_b_ip']}',8081),3);print(s.recv(64).decode())\"",
      "succeed", lambda r: "sidecar_b_open" in r["stdout"], note="sidecar_b listener is up and reachable from its own network")

# ---------------- T1 IPv4 egress ----------------
probe("T1a-https-example", "agent_a", "curl -sS -m 8 -o /dev/null -w '%{http_code}' https://example.com", "fail", http_ok, "C-T1a-outside-https")
probe("T1b-tcp-1.1.1.1-443", "agent_a", "nc -zv -w 4 1.1.1.1 443", "fail", rc0, "C-T1b-outside-tcp1111")
probe("T1c-tcp-8.8.8.8-53", "agent_a", "nc -zv -w 4 8.8.8.8 53", "fail", rc0, "C-T1b-outside-tcp1111")
probe("T1d-icmp-1.1.1.1", "agent_a", "ping -c 1 -W 3 1.1.1.1", "fail", rc0, note="ICMP; no NET_RAW so may also fail for capability reasons")
probe("T1e-edge-peer-outside", "agent_a", f"nc -zv -w 3 {ctx['outside_ip']} 22; nc -zv -w 3 {ctx['outside_ip']} 80", "fail",
      lambda r: "open" in (r["stdout"] + r["stderr"]).lower() or "succeeded" in (r["stdout"] + r["stderr"]).lower())
probe("T1f-routes", "agent_a", "ip route; ip -4 addr", "INFO", rc0, note="routing table of the cell")

# ---------------- T2 DNS ----------------
probe("T2a-dig-default", "agent_a", f"dig +time=3 +tries=1 {ctx['dns_probe_cell']}", "INFO",
      lambda r: "status: NXDOMAIN" in r["stdout"] or dig_answer(r),
      note="response recorded; PASS/FAIL for forwarding is decided from the host-namespace pcap (T2a-pcap)")
probe("T2a2-dig-resolvable-name", "agent_a", "dig +time=3 +tries=1 example.com", "fail", dig_answer, "C-T2b-outside-dig-direct",
      note="a real resolvable name must not get an A answer inside the cell")
probe("T2b-dig-direct-1.1.1.1", "agent_a", "dig +time=3 +tries=1 @1.1.1.1 example.com", "fail", dig_answer, "C-T2b-outside-dig-direct")
probe("T2c-getent-example", "agent_a", "getent hosts example.com", "fail", rc0, "C-T2b-outside-dig-direct")
probe("T2d-resolv-conf", "agent_a", "cat /etc/resolv.conf", "INFO", rc0)

# ---------------- T3 host / gateway-IP / Desktop internal names ----------------
names = ["host.docker.internal", "gateway.docker.internal", "http.docker.internal", "kubernetes.docker.internal", "docker.for.win.localhost"]
probe("T3a-resolve-desktop-names", "agent_a", "for n in " + " ".join(names) + "; do echo \"$n: $(timeout 4 getent hosts $n; echo rc=$?)\"; done", "INFO", rc0,
      note="record what resolves inside the cell")
for n in names:
    probe(f"T3b-connect-{n.split('.')[0]}", "agent_a",
          f"timeout 4 getent hosts {n} >/dev/null || {{ echo unresolvable; exit 1; }}; for p in 80 443 2375 2376 3128 53 6443 8080; do timeout 3 nc -zv -w 2 {n} $p 2>&1 | grep -iE 'open|succeeded' && exit 0; done; exit 1",
          "fail", rc0, "C-T3-outside-host-docker-internal")
probe("T3c-proxy3128-egress", "agent_a", "curl -sS -m 6 -x http://http.docker.internal:3128 -o /dev/null -w '%{http_code}' https://example.com",
      "fail", http_ok, "C-T3-outside-host-docker-internal", note="tries to use Desktop's internal proxy as an egress path")
gw = ctx["cellnet_a_gateway_ip"]
probe("T3d-cellnet-gateway-ip", "agent_a",
      f"[ -z '{gw}' ] && exit 1; for p in 22 53 80 443 2375 2376 3128 5000 8080 9000; do nc -zv -w 2 {gw} $p 2>&1 | grep -iE 'open|succeeded' && exit 0; done; exit 1",
      "fail", rc0, note=f"bridge gateway IP of the internal network: {gw!r}")

# T3e (strict): sweep the subnet's .1 in every variant. If .1 is held by a container, only that
# container's known listeners are allowed (gateway:8080); any other open port = host-side service.
def holder_of(net, ip):
    cp = subprocess.run(["docker", "network", "inspect", "-f",
                         "{{range $k,$v := .Containers}}{{$v.Name}} {{$v.IPv4Address}}{{println}}{{end}}", f"s3iso_{net}"],
                        capture_output=True, text=True)
    for line in cp.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].split("/")[0] == ip:
            return parts[0]
    return None
sub_a = json.loads(subprocess.run(["docker", "network", "inspect", "-f", "{{json .IPAM.Config}}", "s3iso_cellnet_a"],
                                  capture_output=True, text=True).stdout)[0]["Subnet"]
dot1 = ".".join(sub_a.split("/")[0].split(".")[:3]) + ".1"
hold = holder_of("cellnet_a", dot1)
allowed = {"8080"} if hold == "s3iso-gateway-1" else set()
ctx["dot1"] = dot1; ctx["dot1_holder"] = hold or "host-side (bridge address)"
def open_ports_outside_allowed(r):
    ports = set(re.findall(r" (\d+) port \[tcp", r["stdout"]))
    return bool(ports - allowed)
probe("T3e-dot1-full-tcp-sweep", "agent_a", f"nc -zn -w1 {dot1} 1-65535 2>&1 | grep -iE 'succeeded|open'; true",
      "fail", open_ports_outside_allowed,
      note=f"{dot1} held by {ctx['dot1_holder']}; allowed open ports={sorted(allowed)}")
probe("T3f-dot1-udp111", "agent_a", f"nc -znu -w1 {dot1} 111 2>&1 | grep -i succeeded", "fail", rc0,
      note="UDP rpcbind on gateway IP (UDP 'succeeded' = no ICMP unreachable, i.e. port open or filtered)")
probe("T3g-any-ip-on-host-side", "agent_a", "for ip in 172.16.0.1 172.17.0.1 172.18.0.1 172.19.0.1 172.20.0.1 172.21.0.1 192.168.65.1 192.168.65.3 192.168.65.6 192.168.65.7 192.168.65.254; do timeout 2 nc -zn -w1 $ip 111 2>&1 | grep -i succeeded && exit 0; done; exit 1",
      "fail", rc0, note="rpcbind/111 on other known host-side addresses (other bridges, Desktop VM addresses)")
probe("T3h-route-table", "agent_a", "ip route; ip neigh", "INFO", rc0)

# ---------------- T4 IPv6 ----------------
probe("T4a-ipv6-addrs", "agent_a", "ip -6 addr show scope global", "fail", lambda r: "inet6" in r["stdout"],
      note="PASS = no global IPv6 address in the cell")
probe("T4b-ipv6-connect", "agent_a", "curl -6 -sS -m 6 -o /dev/null -w '%{http_code}' https://[2606:4700:4700::1111]", "fail", http_ok)
probe("C-T4-outside-ipv6", "outside", "curl -6 -sS -m 6 -o /dev/null -w '%{http_code}' https://[2606:4700:4700::1111]", "INFO", http_ok,
      note="if this also fails, the host/VM has no IPv6 egress and T4b is weak evidence")

# ---------------- T5 intended path ----------------
probe("T5-gateway-reachable", "agent_a", "curl -sS -m 5 http://gateway:8080/echo", "succeed", lambda r: "gateway-ok" in r["stdout"])

# ---------------- T6 sidecar secret / process isolation ----------------
probe("T6a-read-sidecar-secret", "agent_a", "cat /secrets/cell.key", "fail", lambda r: "DUMMY-CELL-KEY" in r["stdout"], "C-T6-sidecar-reads-secret")
probe("T6b-find-secret-anywhere", "agent_a", "grep -rs DUMMY-CELL-KEY / --exclude-dir=proc --exclude-dir=sys 2>/dev/null | head -1", "fail",
      lambda r: "DUMMY-CELL-KEY" in r["stdout"], "C-T6-sidecar-reads-secret")
probe("T6c-processes-visible", "agent_a", "ps -eo pid,args", "fail", lambda r: "sidecar_a_loopback" in r["stdout"] or "secrets" in r["stdout"],
      note="PASS = sidecar processes not visible (separate PID namespace)")

# ---------------- T7 capabilities / hardening ----------------
probe("T7a-capeff", "agent_a", "grep -E 'Cap(Eff|Prm|Bnd)|NoNewPrivs' /proc/self/status", "INFO", rc0)
probe("T7b-iplink", "agent_a", "ip link set lo mtu 65536", "fail", rc0, "C-T7a-privctl-iplink")
probe("T7c-tcpdump", "agent_a", "timeout 4 tcpdump -i any -c 1 -w /dev/null 2>&1; test $? -ne 1", "fail", rc0, "C-T7b-privctl-tcpdump")
probe("T7d-capeff-zero", "agent_a", "grep CapEff /proc/self/status", "succeed", lambda r: "0000000000000000" in r["stdout"])
probe("T7e-nonewprivs", "agent_a", "grep NoNewPrivs /proc/self/status", "succeed", lambda r: re.search(r"NoNewPrivs:\s+1", r["stdout"]) is not None)
probe("T7f-readonly-rootfs", "agent_a", "touch /probe-write", "fail", rc0)

# ---------------- T8 metadata (local fixtures only; real 169.254.169.254 is NOT contacted) ----------------
probe("T8a-route-169.254.169.254", "agent_a", "ip route get 169.254.169.254", "fail", rc0,
      note="local routing-table lookup only; no packet is sent")
probe("T8b-mdfixture-by-name", "agent_a", "curl -sS -m 5 http://mdfixture/latest/meta-data/token", "fail",
      lambda r: "FAKE-NOT-A-SECRET" in r["stdout"], "C-T8-outside-mdfixture")
probe("T8c-mdfixture-by-ip", "agent_a", f"curl -sS -m 5 http://{ctx['mdfixture_ip']}/latest/meta-data/token", "fail",
      lambda r: "FAKE-NOT-A-SECRET" in r["stdout"], "C-T8-outside-mdfixture")

# ---------------- T9 cross-cell ----------------
probe("T9a-agent_a-to-sidecar_b", "agent_a", f"nc -w 3 {ctx['sidecar_b_ip']} 8081 </dev/null", "fail",
      lambda r: "sidecar_b_open" in r["stdout"], "C-T9-crosscell-ctl")
probe("T9b-agent_b-to-own-sidecar-loopback-of-a", "agent_b", "nc -w 3 127.0.0.1 8081 </dev/null", "fail",
      lambda r: "sidecar_a_loopback" in r["stdout"], "C-T9-own-sidecar-loopback",
      note="loopback in cell B must not reach cell A's sidecar")
probe("T9c-same-net-neighbour", "agent_a", f"nc -w 3 {ctx['neighbour_a2_ip']} 9000 </dev/null", "INFO",
      lambda r: "neighbour_a2_open" in r["stdout"], note="informational: peers on the SAME internal network are reachable")

(RUN / "context.json").write_text(json.dumps(ctx, indent=1))
(RUN / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
summary = {}
for r in results:
    summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
print("SUMMARY", summary)
