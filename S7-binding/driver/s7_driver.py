"""S7 test driver (runs on the host; NOT mounted into any container, so its patterns cannot pollute scans).
Usage: python s7_driver.py <run_dir>. Requires the s7bind project to be up.
Each test records the exact command, exit code and output, plus the PEP binding-log and backend-log
lines written during that test (independent observation). Verdicts: PASS / FAIL / RECORDED;
a negative test counts only if its paired positive control passed (else HARNESS-ERROR)."""
import json, os, subprocess, sys, time
from pathlib import Path

RUN = Path(sys.argv[1]); RUN.mkdir(parents=True, exist_ok=True)
CFG = Path(__file__).resolve().parent.parent / "config"
DC = ["docker", "compose", "-f", str(CFG / "compose.yaml")]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
results = []

def run(args, stdin=None, timeout=120, full=False):
    t0 = time.time()
    cp = subprocess.run(args, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=ENV)
    out = cp.stdout if full else cp.stdout[-3000:]  # evidence records are trimmed; log reads must be complete
    return {"cmd": args, "rc": cp.returncode, "stdout": out, "stderr": cp.stderr[-1500:], "secs": round(time.time() - t0, 2)}

def ex(svc, *args, stdin=None, full=False):
    return run(DC + ["exec", "-T", svc, *args], stdin=stdin, full=full)

def jout(r):
    try:
        return json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:
        return {}

PARSE_ISSUES = []
def lines(svc, path):
    """Read a JSONL log via exec. A line being appended at read time may be incomplete; retry, and keep
    any unparsable raw text as evidence (PARSE_ISSUES -> parse_issues.json) instead of hiding it."""
    for attempt in range(3):
        r = ex(svc, "cat", path, full=True)
        good, bad = [], []
        for l in r["stdout"].splitlines():
            if not l.strip():
                continue
            try:
                good.append(json.loads(l))
            except Exception:
                bad.append(l[:300])
        if not bad:
            return good
        PARSE_ISSUES.append({"svc": svc, "path": path, "attempt": attempt, "bad": bad, "stderr": r["stderr"][:300]})
        time.sleep(0.5)
    return good

def snap():
    return len(lines("pep", "/log/pep.jsonl")), len(lines("backend", "/log/backend_requests.jsonl"))

def delta(s0):
    p, b = lines("pep", "/log/pep.jsonl"), lines("backend", "/log/backend_requests.jsonl")
    calls = []
    for r in b[s0[1]:]:
        try:
            body = json.loads(r["body"])
        except Exception:
            continue
        if isinstance(body, dict) and body.get("method") == "tools/call":
            calls.append(body["params"]["name"])
    return p[s0[0]:], b[s0[1]:], calls

def rec(tid, expected, verdict, control=None, **obs):
    if control is not None:
        c = next((x for x in results if x["id"] == control), None)
        if c is None or c["verdict"] != "PASS":
            verdict = "HARNESS-ERROR" if verdict == "PASS" else verdict
            obs["note"] = "paired positive control did not pass; negative result not credited"
    e = {"id": tid, "expected": expected, "verdict": verdict, "control": control, **obs}
    results.append(e)
    print(f"{tid:34s} {verdict:13s} {json.dumps({k: v for k, v in obs.items() if k in ('summary', 'note')})[:150]}", flush=True)

pki = json.loads((RUN / "pki_public.json").read_text())
X5T_A, X5T_B = pki["x5t#S256"]["cell-a"], pki["x5t#S256"]["cell-b"]
JWT_A_PAYLOAD = None  # read from the harness volume only for scanning; never written to evidence
PROBE = ("import json;t=json.load(open('/secrets/tokens.json'));"
         "kb=lambda f:[l for l in open(f).read().splitlines() if l and not l.startswith('-----')][1];"
         "print(json.dumps({'a':t['JWT_A'].split('.')[1],'a_sig':t['JWT_A'].split('.')[2],'b':t['JWT_B'],"
         "'cert_b':open('/secrets/b.crt').read(),'ka':kb('/secrets/a.key'),'kb':kb('/secrets/b.key')}))")
tok = jout(ex("harness", "python", "-c", PROBE, full=True))
JWT_A_PAYLOAD, JWT_A_SIG, JWT_B_FULL, CERT_B_PEM = tok["a"], tok["a_sig"], tok["b"], tok["cert_b"]
KEY_A_SLICE, KEY_B_SLICE = tok["ka"], tok["kb"]
assert all(len(x) >= 40 for x in (JWT_A_PAYLOAD, JWT_A_SIG, KEY_A_SLICE, KEY_B_SLICE)), "pattern extraction failed"

def bindings(pd):
    return [{k: x.get(k) for k in ("ok", "why", "cert_x5t", "sub", "sid")} for x in pd if x.get("phase") == "binding"]

# ---------------- T1 approved path ----------------
s0 = snap(); r = ex("agent_a", "python", "/harness/s7_agent.py", "call", "echo"); pd, bd, calls = delta(s0); o = jout(r)
b = bindings(pd)
ok = o.get("ok") and o.get("texts") == ["echo-ok"] and b and all(x["ok"] and x["cert_x5t"] == X5T_A and x["sub"] == "agent:cell-a" for x in b) and calls == ["echo"]
rec("S7-T1-approved-path", "agent A -> sidecar -> terminator -> PEP -> backend succeeds; PEP logs binding match for cell A; identity agent:cell-a",
    "PASS" if ok else "FAIL", exec=r, client=o, pep_bindings=b, backend_tool_calls=calls,
    tool_identity=[x.get("identity") for x in pd if x.get("phase") == "tool-pre"], summary=f"bindings={len(b)} calls={calls}")

# ---------------- T2 cross-cell replay ----------------
s0 = snap(); r = ex("agent_b", "python", "/harness/s7_agent.py", "call", "echo"); pd, bd, calls = delta(s0); o = jout(r); b = bindings(pd)
rec("S7-T2-ctl-cellB-own-token", "cell B (cert B + JWT_B) accepted (positive control)",
    "PASS" if o.get("ok") and b and all(x["ok"] and x["cert_x5t"] == X5T_B for x in b) and calls == ["echo"] else "FAIL",
    exec=r, client=o, pep_bindings=b, backend_tool_calls=calls)
s0 = snap(); r = ex("agent_c", "python", "/harness/s7_agent.py", "call", "echo"); pd, bd, calls = delta(s0); o = jout(r); b = bindings(pd)
rec("S7-T2-JWT_A-in-certB-sidecar", "rejected (cnf mismatch); backend receives no tool call",
    "PASS" if not o.get("ok") and b and all((not x["ok"]) and "cnf mismatch" in x["why"] for x in b) and not calls else "FAIL",
    control="S7-T2-ctl-cellB-own-token", exec=r, client=o, pep_bindings=b, backend_tool_calls=calls, summary=str({x['why'][:40] for x in b}))

def hmatrix(tid, cert, token, extra, want_ok, expect_why=None, control=None, expected=""):
    s0 = snap()
    args = ["python", "/harness/s7_harness.py", cert, token] + ([json.dumps(extra)] if extra else [])
    r = ex("harness", *args); o = jout(r); pd, bd, calls = delta(s0); b = bindings(pd)
    got_ok = bool(o.get("mcp", {}).get("ok"))
    if o.get("mcp", {}).get("skipped"):  # duplicate-header case: only the raw request carries the duplicates
        v = (not want_ok) and o.get("raw_status") in (400, 401) and "echo" not in calls and all(not x["ok"] for x in b)
        rec(tid, expected, "PASS" if v else "FAIL", control=control, exec=r, client=o, pep_bindings=b, backend_tool_calls=calls,
            summary=f"raw={o.get('raw_status')} body={str(o.get('raw_body'))[:60]!r} why={sorted({x['why'][:48] for x in b})}")
        return
    if want_ok:
        v = got_ok and o.get("raw_status") != 401 and b and all(x["ok"] for x in b) and "echo" in calls
    else:
        v = (not got_ok) and o.get("raw_status") in (400, 401, None) and "echo" not in calls and all(not x["ok"] for x in b)
        if expect_why == "no-pep":
            v = v and not b  # rejected by the terminator: nothing may reach the PEP
        elif expect_why:
            v = v and b and all(expect_why in x["why"] for x in b)
    rec(tid, expected, "PASS" if v else "FAIL", control=control, exec=r, client=o, pep_bindings=b, backend_tool_calls=calls,
        summary=f"raw={o.get('raw_status')} mcp_ok={got_ok} why={sorted({x['why'][:48] for x in b})}")

hmatrix("S7-T2-ctl-certA-JWT_A", "a", "JWT_A", None, True, expected="cert A + JWT_A accepted (positive control for the matrix)")
hmatrix("S7-T2-ctl-certB-JWT_B", "b", "JWT_B", None, True, expected="cert B + JWT_B accepted (positive control)")
hmatrix("S7-T2-certB-JWT_A", "b", "JWT_A", None, False, "cnf mismatch", "S7-T2-ctl-certB-JWT_B", "stolen JWT_A replayed with cert B: rejected")
hmatrix("S7-T2-certA-JWT_B", "a", "JWT_B", None, False, "cnf mismatch", "S7-T2-ctl-certA-JWT_A", "JWT_B replayed with cert A: rejected")

# ---------------- T3 bypassing the sidecar ----------------
for mode in ["no-cert", "rogue-cert", "plain-http"]:
    s0 = snap(); r = ex("agent_a", "python", "/harness/s7_agent.py", "tls", mode); pd, bd, calls = delta(s0); o = jout(r)
    head = o.get("response_head", "")
    rejected = ("error" in o) or head.startswith("HTTP/1.1 400") or head.startswith("HTTP/1.1 495") or head.startswith("HTTP/1.1 496")
    rec(f"S7-T3-agent-direct-{mode}", "terminator rejects; nothing reaches the PEP", "PASS" if rejected and not pd and not calls else "FAIL",
        control="S7-T1-approved-path", exec=r, client=o, pep_log_delta=len(pd), summary=(head.splitlines()[0] if head else o.get("error", ""))[:90])
hmatrix("S7-T3-harness-no-cert", "none", "JWT_A", None, False, "no-pep", "S7-T2-ctl-certA-JWT_A", "valid JWT_A but no client cert: terminator rejects; PEP never sees it")
hmatrix("S7-T3-harness-rogue-cert", "rogue", "JWT_A", None, False, "no-pep", "S7-T2-ctl-certA-JWT_A", "self-signed cert with CN=cell-a + JWT_A: terminator rejects")

# ---------------- T4 header spoofing / direct reachability ----------------
from urllib.parse import quote
spoof = quote(CERT_B_PEM, safe="")
s0 = snap(); r = ex("agent_a", "python", "/harness/s7_agent.py", "call", "echo", json.dumps({"X-Client-Cert": spoof})); pd, bd, calls = delta(s0); o = jout(r); b = bindings(pd)
rec("S7-T4a-agent-spoofs-X-Client-Cert", "terminator overwrites; PEP sees cert A only (call bound to cell A, never to cert B)",
    "PASS" if b and all(x["cert_x5t"] == X5T_A for x in b) and not any(x["cert_x5t"] == X5T_B for x in b) else "FAIL",
    control="S7-T1-approved-path", exec={**r, "cmd": r["cmd"][:-1] + ["<escaped cert B PEM>"]}, client=o, pep_bindings=b,
    summary=f"call_ok={o.get('ok')} x5t_seen={sorted({x['cert_x5t'][:10] for x in b})}")
s0 = snap(); r = ex("agent_a", "python", "/harness/s7_agent.py", "call", "echo", json.dumps({"Authorization": "Bearer " + JWT_B_FULL})); pd, bd, calls = delta(s0); o = jout(r); b = bindings(pd)
rec("S7-T4b-agent-supplies-other-Authorization", "sidecar replaces it; PEP sees sid sess-A-1 / agent:cell-a only",
    "PASS" if b and all(x["sid"] == "sess-A-1" and x["sub"] == "agent:cell-a" for x in b) else "FAIL",
    control="S7-T1-approved-path", exec={**r, "cmd": r["cmd"][:-1] + ["<Authorization: Bearer JWT_B>"]}, client=o, pep_bindings=b,
    summary=f"call_ok={o.get('ok')} sids={sorted({str(x['sid']) for x in b})}")
hmatrix("S7-T4c-harness-spoofs-X-Client-Cert", "a", "JWT_B", {"X-Client-Cert": spoof}, False, "cnf mismatch", "S7-T2-ctl-certA-JWT_A",
        "cert A + JWT_B + client-supplied X-Client-Cert (cert B): header overwritten, so JWT_B does not match and is rejected")
hmatrix("S7-T4d-duplicate-Authorization", "a", "none", {"Authorization": ["@JWT_A", "@JWT_B"]}, False, None, "S7-T2-ctl-certA-JWT_A",
        "two Authorization headers: rejected by the terminator (400) or the PEP (401); never accepted")
def ips(svc):
    r = run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", f"s7bind-{svc}-1"])
    return r["stdout"].split()
for tgt, port in [("pep", 8000), ("backend", 9000)] + [(ip, 8000) for ip in ips("pep")] + [(ip, 9000) for ip in ips("backend")]:
    r = ex("agent_a", "python", "/harness/s7_agent.py", "reach", tgt, str(port)); o = jout(r)
    rec(f"S7-T4e-agent-direct-{tgt}", f"{tgt}:{port} unreachable from the cell", "PASS" if o.get("reached") is False else "FAIL",
        control="S7-T1-approved-path", exec=r, client=o, summary=o.get("error", "")[:80])
for tgt in ["pep"] + ips("pep"):
    r = ex("harness", "python", "/harness/s7_agent.py", "reach", tgt, "8000"); o = jout(r)
    rec(f"S7-T4f-testnet-direct-pep-{tgt}", "PEP unreachable from the test network (only the terminator reaches it)",
        "PASS" if o.get("reached") is False else "FAIL", exec=r, client=o, summary=o.get("error", "")[:80])

# ---------------- T5 credential confinement ----------------
pats = [JWT_A_PAYLOAD, JWT_A_SIG, KEY_A_SLICE, KEY_B_SLICE, "DUMMY-DOWNSTREAM-TOOL-KEY"]
r = ex("agent_a", "python", "/harness/s7_agent.py", "scan", stdin=json.dumps(pats)); o = jout(r)
c1 = ex("sidecar_a", "grep", "-rlF", JWT_A_PAYLOAD, "/secrets"); c2 = ex("sidecar_a", "grep", "-rlF", KEY_A_SLICE, "/secrets")
c3 = ex("backend", "printenv", "TOOL_API_KEY")
ctl_ok = "auth.conf" in c1["stdout"] and "cell.key" in c2["stdout"] and "DUMMY-DOWNSTREAM-TOOL-KEY" in c3["stdout"]
rec("S7-T5-ctl-secrets-exist-elsewhere", "JWT_A and key present in sidecar_a /secrets; tool key present in backend env (positive control)",
    "PASS" if ctl_ok else "FAIL", jwt_in=c1["stdout"].split(), key_in=c2["stdout"].split(), backend_env_has_tool_key="DUMMY-DOWNSTREAM-TOOL-KEY" in c3["stdout"])
rec("S7-T5-agent-holds-no-secrets", "no JWT (payload or signature), cell private key (A or B) or downstream tool key in agent env / filesystem / /proc",
    "PASS" if o.get("cmd") == "scan" and o.get("n_patterns") == 5 and not o.get("hits") and o.get("secrets_dir_exists") is False else "FAIL",
    control="S7-T5-ctl-secrets-exist-elsewhere", exec={**r, "cmd": r["cmd"]}, client=o, summary=f"hits={o.get('hits')} procs={o.get('visible_processes')}")
blog = lines("backend", "/log/backend_requests.jsonl")
leak = [i for i, x in enumerate(blog) if JWT_A_PAYLOAD in json.dumps(x) or "x-client-cert" in x["headers"] or "authorization" in x["headers"]]
rec("S7-T5b-downstream-confinement", "backend never receives the agent JWT, an Authorization header or the client certificate",
    "PASS" if blog and not leak else "FAIL", n_backend_requests=len(blog), leaking_request_indexes=leak[:10], summary=f"requests={len(blog)} leaks={len(leak)}")

# ---------------- T6 streaming ----------------
n, d = 5, 0.6
r = ex("agent_a", "python", "/harness/s7_agent.py", "stream", str(n), str(d)); o = jout(r); arr = o.get("progress_arrivals_s", [])
incremental = len(arr) == n and all(b > a for a, b in zip(arr, arr[1:])) and (arr[-1] - arr[0]) >= (n - 1) * d * 0.7
rec("S7-T6-streaming", f"{n} progress events arrive incrementally (~{d}s apart) through sidecar + terminator + PEP", "PASS" if o.get("ok") and incremental else "FAIL",
    exec=r, client=o, summary=f"arrivals={arr} total={o.get('total_s')}")

# ---------------- T7 token validity ----------------
for tname, why in [("JWT_A_expired", "ExpiredSignature"), ("JWT_A_revoked", "session revoked"), ("JWT_A_tampered", "InvalidSignature"),
                   ("JWT_A_alg_none", "jwt rejected"), ("JWT_A_rogue_issuer", "InvalidSignature"), ("JWT_A_wrong_aud", "InvalidAudience"),
                   ("JWT_A_no_cnf", "MissingRequiredClaim"), ("none", "exactly 1 Bearer")]:
    hmatrix(f"S7-T7-{tname}", "a", tname, None, False, why, "S7-T2-ctl-certA-JWT_A", f"cert A + {tname}: rejected by the PEP ({why})")

# runtime revocation of the live session: add sess-A-1 -> agent A rejected; restore -> accepted again
VOL = "s7bind_sec_pep"
NG = os.environ["NGINX_IMAGE"]
w1 = run(["docker", "run", "--rm", "-v", f"{VOL}:/v", "--entrypoint", "sh", NG, "-c", "echo sess-A-1 >> /v/revoked.txt; cat /v/revoked.txt"])
s0 = snap(); r = ex("agent_a", "python", "/harness/s7_agent.py", "call", "echo"); pd, bd, calls = delta(s0); o = jout(r); b = bindings(pd)
rec("S7-T7-runtime-revocation", "after sess-A-1 is added to the revocation list, agent A's next call is rejected",
    "PASS" if not o.get("ok") and b and all("session revoked" in x["why"] for x in b) and not calls else "FAIL",
    control="S7-T1-approved-path", revoke_write=w1, client=o, pep_bindings=b, summary=str({x['why'] for x in b}))
w2 = run(["docker", "run", "--rm", "-v", f"{VOL}:/v", "--entrypoint", "sh", NG, "-c", "printf 'sess-A-revoked\\n' > /v/revoked.txt; cat /v/revoked.txt"])
r = ex("agent_a", "python", "/harness/s7_agent.py", "call", "echo"); o = jout(r)
rec("S7-T7-runtime-revocation-restore", "after removal, agent A is accepted again", "PASS" if o.get("ok") else "FAIL", restore_write=w2, client=o)

(RUN / "parse_issues.json").write_text(json.dumps(PARSE_ISSUES, indent=1))
(RUN / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
s = {}
for r in results:
    s[r["verdict"]] = s.get(r["verdict"], 0) + 1
print("SUMMARY", s)
