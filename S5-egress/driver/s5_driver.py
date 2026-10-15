"""S5 driver (host side). Usage: python s5_driver.py <run_dir>. Requires the s5egress project up and the DNS
capture container `s5cap` running in egress's netns (started by run_s5.sh).
Independent observation: allowed-srv / denied-srv log every TCP accept, HTTP request and UDP datagram;
the pcap in egress's netns records every DNS query the proxy makes. A negative test counts only if its
paired positive control passed."""
import json, os, subprocess, sys, time
from pathlib import Path

RUN = Path(sys.argv[1])
DC = ["docker", "compose", "-f", str(Path(__file__).resolve().parent.parent / "config" / "compose.yaml")]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
PX = "http://sess-1:tok-good-1@egress:8080"
results = []

def run(args, timeout=120, stdin=None):
    t0 = time.time()
    cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=ENV, input=stdin)
    return {"cmd": args, "rc": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr[-1500:], "secs": round(time.time() - t0, 2)}

def ex(svc, *a):
    return run(DC + ["exec", "-T", svc, *a])

def trim(r):
    return {**r, "stdout": r["stdout"][-2000:]}

def srvlog(name):
    r = ex("allowed-srv", "cat", f"/log/{name}.jsonl")
    return [json.loads(l) for l in r["stdout"].splitlines() if l.strip()]

def egresslog():
    r = ex("egress", "cat", "/log/egress.jsonl")
    return [json.loads(l) for l in r["stdout"].splitlines() if l.strip()]

def ip(svc, net):
    r = run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", f"s5egress-{svc}-1"])
    return json.loads(r["stdout"])[f"s5egress_{net}"]["IPAddress"]

EGRESS_EDGE, OUTSIDE = ip("egress", "edge"), ip("outside", "edge")
ALLOWED_IP, DENIED_IP = ip("allowed-srv", "edge"), ip("denied-srv", "edge")

def snap():
    return len(srvlog("allowed-srv")), len(srvlog("denied-srv")), len(egresslog())

def delta(s):
    a, d, e = srvlog("allowed-srv"), srvlog("denied-srv"), egresslog()
    return a[s[0]:], d[s[1]:], e[s[2]:]

def rec(tid, expected, verdict, control=None, **obs):
    if control:
        c = next((x for x in results if x["id"] == control), None)
        if c is None or c["verdict"] != "PASS":
            verdict = "HARNESS-ERROR" if verdict == "PASS" else verdict
            obs["note"] = "paired positive control did not pass; negative result not credited"
    results.append({"id": tid, "expected": expected, "verdict": verdict, "control": control, **obs})
    print(f"{tid:34s} {verdict:13s} {obs.get('summary', '')}"[:200], flush=True)

def from_egress(entries):
    return [e for e in entries if e.get("peer") == EGRESS_EDGE]

def curl(*a, svc="sandbox"):
    return ex(svc, "curl", "-s", "-S", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}", *a)

# ---------------- positive controls ----------------
s = snap(); r = curl("http://denied-srv/", svc="outside"); a, d, e = delta(s)
rec("C-denied-srv-logs-contact", "outside -> denied-srv directly is logged (the observer works)",
    "PASS" if r["stdout"] == "200" and any(x["ev"] == "tcp-accept" for x in d) else "FAIL", exec=trim(r), denied_log=d, summary=f"code={r['stdout']} logged={len(d)}")
s = snap(); r = curl("http://allowed-srv/", svc="outside"); a, d, e = delta(s)
rec("C-allowed-direct-from-edge", "outside -> allowed-srv directly works (target is up)", "PASS" if r["stdout"] == "200" else "FAIL", exec=trim(r))
r = ex("outside", "python", "-c", f"import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);[s.sendto(b'x',('{ALLOWED_IP}',p)) for p in (443,9999)]")
time.sleep(1); u = [x for x in srvlog("allowed-srv") if x["ev"] == "udp" and x["peer"] == OUTSIDE]
rec("C-udp-observable", "UDP from outside to allowed-srv :443 and :9999 is logged", "PASS" if {x["port"] for x in u} >= {443, 9999} else "FAIL", exec=trim(r), udp=u)

# ---------------- T1 allowed ----------------
s = snap(); r = curl("-x", PX, "http://allowed-srv/"); a, d, e = delta(s)
rec("T1-allowed-http", "200; logged by allowed-srv from the egress IP; egress logs allow with session",
    "PASS" if r["stdout"] == "200" and any(x["ev"] == "http" for x in from_egress(a)) and any(x["ev"] == "allow" and x["sess"] == "sess-1" for x in e) else "FAIL",
    exec=trim(r), allowed_log=a, egress=e, summary=f"code={r['stdout']}")
s = snap(); r = curl("-k", "-x", PX, "https://allowed-srv/"); a, d, e = delta(s)
rec("T1b-allowed-connect", "CONNECT allowed-srv:443 tunnels (no interception); allowed-srv logs the TLS request",
    "PASS" if r["stdout"] == "200" and any(x["ev"] == "http" for x in from_egress(a)) and any(x["ev"] == "allow-connect" for x in e) else "FAIL",
    exec=trim(r), allowed_log=a, egress=e, summary=f"code={r['stdout']}")

# ---------------- T2 CONNECT denied ----------------
for tid, url in [("T2-connect-denied-name", "https://denied-srv/"), ("T2b-connect-denied-ip", f"https://{DENIED_IP}/"),
                 ("T2c-connect-allowed-ip-literal", f"https://{ALLOWED_IP}/"), ("T2d-connect-suffix-trick", "https://allowed-srv.evil.test/"),
                 ("T2e-connect-case-trailing-dot", "https://DENIED-SRV./")]:
    s = snap(); r = curl("-k", "-x", PX, url); a, d, e = delta(s)
    ok = ("403" in r["stderr"] or r["stdout"] in ("403", "000")) and not from_egress(d) and not from_egress(a) and any(x["ev"] == "deny" and x["code"] == 403 for x in e)
    rec(tid, f"CONNECT {url}: 403 from proxy; zero contact at either server", "PASS" if ok else "FAIL", control="C-denied-srv-logs-contact",
        exec=trim(r), egress=e, denied_contacts=from_egress(d), allowed_contacts=from_egress(a), summary=f"stderr={r['stderr'].strip()[:70]!r}")

# ---------------- T3 plain HTTP denied ----------------
for tid, args in [("T3-http-denied", ["http://denied-srv/"]), ("T3b-userinfo-trick", ["http://allowed-srv@denied-srv/"]),
                  ("T3c-host-header-confusion", ["-H", "Host: denied-srv", "http://allowed-srv/"])]:
    s = snap(); r = curl("-x", PX, *args); a, d, e = delta(s)
    if tid == "T3c-host-header-confusion":  # allowed by destination; must connect ONLY to allowed-srv
        ok = not from_egress(d) and r["stdout"] == "200" and any(x["ev"] == "http" for x in from_egress(a))
        exp = "absolute-URL host decides; connection goes only to allowed-srv; denied-srv never contacted"
    else:
        ok = r["stdout"] == "403" and not from_egress(d) and any(x["ev"] == "deny" for x in e)
        exp = "403 from proxy; zero contact at denied-srv"
    rec(tid, exp, "PASS" if ok else "FAIL", control="C-denied-srv-logs-contact", exec=trim(r), egress=e, denied_contacts=from_egress(d),
        summary=f"code={r['stdout']} denied_contacts={len(from_egress(d))}")

# ---------------- T4 redirect ----------------
s = snap(); r = curl("-L", "-x", PX, "http://allowed-srv/redirect"); a, d, e = delta(s)
ok = r["stdout"] == "403" and any(x.get("path") == "/redirect" for x in from_egress(a)) and not from_egress(d)
rec("T4-redirect-to-denied", "first hop served by allowed-srv; second hop (denied-srv) blocked; zero contact at denied-srv",
    "PASS" if ok else "FAIL", control="C-denied-srv-logs-contact", exec=trim(r), egress=e, summary=f"final={r['stdout']}")

# ---------------- T5 / T10 bypass without proxy ----------------
for tid, args in [("T5-noproxy-name", ["--noproxy", "*", "http://allowed-srv/"]), ("T5b-noproxy-ip", ["--noproxy", "*", f"http://{ALLOWED_IP}/"])]:
    s = snap(); r = curl(*args); a, d, e = delta(s)
    rec(tid, "direct request without proxy fails; allowed-srv sees nothing from the cell", "PASS" if r["stdout"] == "000" and not a else "FAIL",
        control="C-allowed-direct-from-edge", exec=trim(r), summary=r["stderr"].strip()[:80])
probe = ("import socket,json;res={}\n"
         f"for p in (80,443):\n  try: socket.create_connection(('{ALLOWED_IP}',p),3).close(); res['tcp%d'%p]='connected'\n  except Exception as e: res['tcp%d'%p]=type(e).__name__+': '+str(e)\n"
         f"s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\nfor p in (443,9999):\n  try: s.sendto(b'x',('{ALLOWED_IP}',p)); res['udp%d'%p]='sent'\n  except Exception as e: res['udp%d'%p]=type(e).__name__+': '+str(e)\n"
         "print(json.dumps(res))")
s = snap(); r = ex("sandbox", "python", "-c", probe); time.sleep(1); a, d, e = delta(s)
rec("T10-raw-tcp-udp", "raw TCP 80/443 and UDP 443 (QUIC) / 9999 from the cell reach nothing", "PASS" if a == [] and "connected" not in r["stdout"] else "FAIL",
    control="C-udp-observable", exec=trim(r), allowed_log=a, summary=r["stdout"].strip()[:150])

# ---------------- T6 proxy auth ----------------
for tid, px, want in [("T6-no-credentials", "http://egress:8080", "407"), ("T6b-bad-credentials", "http://sess-1:wrong@egress:8080", "407"),
                      ("T6c-unknown-session", "http://sess-9:tok-good-1@egress:8080", "407")]:
    s = snap(); r = curl("-x", px, "http://allowed-srv/"); a, d, e = delta(s)
    rec(tid, "407; allowed-srv never contacted", "PASS" if r["stdout"] == want and not a else "FAIL", control="T1-allowed-http", exec=trim(r), egress=e,
        summary=f"code={r['stdout']}")
s = snap(); r = curl("-k", "-x", "http://egress:8080", "https://allowed-srv/"); a, d, e = delta(s)
rec("T6d-connect-no-credentials", "CONNECT without credentials: 407; no tunnel", "PASS" if "407" in r["stderr"] and not a else "FAIL", control="T1b-allowed-connect",
    exec=trim(r), summary=r["stderr"].strip()[:80])

# ---------------- T7 byte budget ----------------
codes = []; s = snap()
for i in range(5):
    r = ex("sandbox", "python", "-c", "import subprocess,sys;p=subprocess.run(['curl','-s','-m','20','-o','/dev/null','-w','%{http_code}','-x','" + PX +
           "','--data-binary','@-','http://allowed-srv/upload'],input=b'\\0'*1000000,capture_output=True);print(p.stdout.decode())")
    codes.append(r["stdout"].strip())
a, d, e = delta(s); posts = [x for x in from_egress(a) if x.get("method") == "POST"]
rec("T7-byte-budget", "budget 3,000,000 B: three 1 MB POSTs pass, the 4th and 5th are blocked; allowed-srv receives exactly 3",
    "PASS" if codes == ["200", "200", "200", "403", "403"] and len(posts) == 3 and all(p["bytes"] == 1000000 for p in posts) else "FAIL",
    codes=codes, posts_at_server=len(posts), egress=[x for x in e if x["ev"] in ("allow", "deny")], summary=f"codes={codes} posts={len(posts)}")

# ---------------- T8 SSE ----------------
sse = ("import subprocess,time,json;t0=time.monotonic();p=subprocess.Popen(['curl','-sN','-x','" + PX + "','http://allowed-srv/sse'],stdout=subprocess.PIPE);ts=[]\n"
       "for line in p.stdout:\n  if line.startswith(b'data:'): ts.append(round(time.monotonic()-t0,3))\n"
       "print(json.dumps(ts))")
r = ex("sandbox", "python", "-c", sse)
try:
    ts = json.loads(r["stdout"].strip())
except Exception:
    ts = []
rec("T8-sse", "5 events arrive incrementally (~0.6 s apart) through the proxy",
    "PASS" if len(ts) == 5 and all(b > a for a, b in zip(ts, ts[1:])) and ts[-1] - ts[0] >= 4 * 0.6 * 0.7 else "FAIL", exec=trim(r), arrivals=ts, summary=f"arrivals={ts}")

(RUN / "results.jsonl").write_text("\n".join(json.dumps(x) for x in results) + "\n")
(RUN / "context.json").write_text(json.dumps({"egress_edge_ip": EGRESS_EDGE, "outside_ip": OUTSIDE, "allowed_ip": ALLOWED_IP, "denied_ip": DENIED_IP}, indent=1))
c = {}
for x in results:
    c[x["verdict"]] = c.get(x["verdict"], 0) + 1
print("SUMMARY", c)
