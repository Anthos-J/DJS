"""S6 driver (host side). Usage: python s6_driver.py <run_dir>. Requires the s6model project up.
Independent observation = the mock provider's request log (every TCP accept and request, logged before replying).
Each rejection test has a paired positive control: the same request minus the offending element is forwarded."""
import json, os, subprocess, sys, time
from pathlib import Path

RUN = Path(sys.argv[1])
DC = ["docker", "compose", "-f", str(Path(__file__).resolve().parent.parent / "config" / "compose.yaml")]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
PROXY = "http://model-proxy:8080"
KEY = "DUMMY-PROVIDER-KEY-4b9d"
results = []

def run(args, stdin=None):
    cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", input=stdin, env=ENV, timeout=120)
    return {"cmd": args, "rc": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr[-800:]}

def plog():
    r = run(DC + ["exec", "-T", "mock-provider", "cat", "/log/provider.jsonl"])
    return [json.loads(l) for l in r["stdout"].splitlines() if l.strip()]

def send(svc, path, body, headers=None, **kw):
    spec = {"url": (PROXY if svc == "agent" else "http://mock-provider:9000") + path, "body": body, "headers": headers or {}, **kw}
    n0 = len(plog())
    r = run(DC + ["exec", "-T", svc, "python", "/harness/req.py"], stdin=json.dumps(spec))
    time.sleep(0.2)
    got = [x for x in plog()[n0:] if x["ev"] == "request"]
    try:
        out = json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:
        out = {"error": "no output", "stderr": r["stderr"]}
    return out, got, {"spec": spec, "rc": r["rc"]}

def rec(tid, expected, verdict, control=None, **obs):
    if control:
        c = next((x for x in results if x["id"] == control), None)
        if c is None or c["verdict"] != "PASS":
            verdict = "HARNESS-ERROR" if verdict == "PASS" else verdict
            obs["note"] = "paired positive control did not pass; negative result not credited"
    results.append({"id": tid, "expected": expected, "verdict": verdict, "control": control, **obs})
    print(f"{tid:36s} {verdict:13s} {obs.get('summary', '')}"[:210], flush=True)

def forwarded_ok(out, got, api="anthropic"):
    if out.get("status") != 200 or len(got) != 1:
        return False
    h = got[0]["headers"]
    key_ok = h.get("x-api-key") == KEY if api == "anthropic" else h.get("authorization") == f"Bearer {KEY}"
    return key_ok

MSG = '"model":"m","max_tokens":16,"messages":[{"role":"user","content":"hi"}]'
CUSTOM = '{"name":"lookup","description":"d","input_schema":{"type":"object"}}'

# ---------------- controls ----------------
out, got, ev = send("outside", "/v1/messages", "{" + MSG + "}")
rec("C-provider-observes-direct", "outside -> mock provider directly: request logged (observer works)",
    "PASS" if out.get("status") == 200 and len(got) == 1 else "FAIL", out=out, logged=len(got), summary=f"status={out.get('status')} logged={len(got)}")

# ---------------- T1 forwarding + key injection ----------------
cases_ok = [
    ("T1-anthropic-custom-tools", "/v1/messages", "{" + MSG + ',"tools":[' + CUSTOM + "]}", None, "anthropic"),
    ("T1b-anthropic-type-custom", "/v1/messages", "{" + MSG + ',"tools":[{"type":"custom","name":"x","input_schema":{"type":"object"}}]}', None, "anthropic"),
    ("T1c-client-key-replaced", "/v1/messages", "{" + MSG + "}", {"x-api-key": "ATTACKER-KEY", "Authorization": "Bearer ATTACKER"}, "anthropic"),
    ("T4-ctl-openai-function", "/v1/responses", '{"model":"m","input":"hi","tools":[{"type":"function","name":"f","parameters":{"type":"object"}}]}', None, "openai"),
]
for tid, path, body, hdr, api in cases_ok:
    out, got, ev = send("agent", path, body, hdr)
    h = got[0]["headers"] if got else {}
    ok = forwarded_ok(out, got, api) and "ATTACKER" not in json.dumps(h)
    rec(tid, "forwarded; provider receives the proxy-injected key and never a client-supplied one", "PASS" if ok else "FAIL",
        out=out, provider_headers={k: v for k, v in h.items() if k in ("x-api-key", "authorization")}, request=ev,
        summary=f"status={out.get('status')} key={'ok' if forwarded_ok(out, got, api) else 'BAD'} n={len(got)}")
out, got, ev = send("agent", "/v1/messages", "{" + MSG + "}")
rec("T1d-cell-sent-no-key", "the agent's request carried no key; the provider still received the injected key",
    "PASS" if forwarded_ok(out, got) and "x-api-key" not in ev["spec"]["headers"] else "FAIL", out=out)

# canonical forwarding: provider receives exactly the checked, re-serialized body
body_ws = '{ "model" : "m" , "max_tokens":16, "messages":[{"role":"user","content":"hi"}], "tools":[' + CUSTOM + '] }'
out, got, ev = send("agent", "/v1/messages", body_ws)
canon = json.dumps(json.loads(body_ws), separators=(",", ":"), ensure_ascii=True)
rec("T1e-canonical-body", "provider receives the re-serialized (checked) body, complete; client gets 200 (not a timeout)",
    "PASS" if got and got[0]["body"] == canon and out.get("status") == 200 else "FAIL",
    out=out, summary=f"status={out.get('status')} match={bool(got) and got[0]['body'] == canon}")
# T1f: canonical form LONGER than the raw body (non-ASCII becomes \uXXXX). A stale Content-Length would truncate it.
body_u = '{"model":"m","max_tokens":16,"messages":[{"role":"user","content":"héllo üñîçødé"}]}'
out, got, ev = send("agent", "/v1/messages", body_u)
canon_u = json.dumps(json.loads(body_u), separators=(",", ":"), ensure_ascii=True)
rec("T1f-canonical-longer-than-raw", "non-ASCII body: provider receives the COMPLETE canonical body (no truncation); client gets 200",
    "PASS" if got and got[0]["body"] == canon_u and out.get("status") == 200 else "FAIL",
    out=out, provider_body=(got[0]["body"] if got else None),
    summary=f"status={out.get('status')} complete={bool(got) and got[0]['body'] == canon_u}")

# ---------------- rejections (each must leave ZERO requests at the provider) ----------------
WS = '{"type":"web_search_20260209","name":"web_search"}'
rejects = [
    ("T2-anthropic-web-search", "/v1/messages", "{" + MSG + ',"tools":[' + WS + "]}", {}, "T1-anthropic-custom-tools"),
    ("T2b-anthropic-mixed-tools", "/v1/messages", "{" + MSG + ',"tools":[' + CUSTOM + "," + WS + "]}", {}, "T1-anthropic-custom-tools"),
    ("T2c-anthropic-code-exec", "/v1/messages", "{" + MSG + ',"tools":[{"type":"code_execution_20250825","name":"code_execution"}]}', {}, "T1-anthropic-custom-tools"),
    ("T3-mcp-servers", "/v1/messages", "{" + MSG + ',"mcp_servers":[{"type":"url","url":"https://evil.example/mcp","name":"x"}]}', {}, "T1c-client-key-replaced"),
    ("T4-openai-web-search", "/v1/responses", '{"model":"m","input":"hi","tools":[{"type":"web_search"}]}', {}, "T4-ctl-openai-function"),
    ("T4b-openai-mcp", "/v1/responses", '{"model":"m","input":"hi","tools":[{"type":"mcp","server_label":"x","server_url":"https://evil.example"}]}', {}, "T4-ctl-openai-function"),
    ("T4c-openai-no-type", "/v1/responses", '{"model":"m","input":"hi","tools":[{"name":"f"}]}', {}, "T4-ctl-openai-function"),
    ("T5-unknown-tool-type", "/v1/messages", "{" + MSG + ',"tools":[{"type":"future_tool_20990101","name":"z"}]}', {}, "T1-anthropic-custom-tools"),
    ("T5b-unknown-top-level", "/v1/messages", "{" + MSG + ',"container":"abc"}', {}, "T1c-client-key-replaced"),
    ("T5c-unknown-tool-field", "/v1/messages", "{" + MSG + ',"tools":[{"name":"x","input_schema":{},"server_url":"https://evil"}]}', {}, "T1-anthropic-custom-tools"),
    ("T6-duplicate-tools-key", "/v1/messages", "{" + MSG + ',"tools":[' + CUSTOM + '],"tools":[' + WS + "]}", {}, "T1-anthropic-custom-tools"),
    ("T6b-duplicate-nested-type", "/v1/messages", "{" + MSG + ',"tools":[{"type":"custom","name":"x","input_schema":{},"type":"web_search_20260209"}]}', {}, "T1b-anthropic-type-custom"),
    ("T6c-mixed-case-type", "/v1/messages", "{" + MSG + ',"tools":[{"type":"Custom","name":"x","input_schema":{}}]}', {}, "T1b-anthropic-type-custom"),
    ("T6d-openai-mixed-case", "/v1/responses", '{"model":"m","input":"hi","tools":[{"type":"Function","name":"f"}]}', {}, "T4-ctl-openai-function"),
    ("T6e-escaped-key-name", "/v1/messages", "{" + MSG + ',"\\u0074ools":[' + WS + "]}", {}, "T1-anthropic-custom-tools"),
    ("T6f-key-with-space", "/v1/messages", "{" + MSG + ',"tools ":[' + WS + "]}", {}, "T1-anthropic-custom-tools"),
    ("T6g-tools-as-object", "/v1/messages", "{" + MSG + ',"tools":{"0":' + WS + "}}", {}, "T1-anthropic-custom-tools"),
    ("T6h-top-level-array", "/v1/messages", "[{" + MSG + "}]", {}, "T1c-client-key-replaced"),
    ("T6i-not-json", "/v1/messages", "model=m&tools=web_search", {}, "T1c-client-key-replaced"),
    ("T6j-other-route", "/v1/files", "{}", {}, "T1c-client-key-replaced"),
]
for tid, path, body, hdr, ctl in rejects:
    out, got, ev = send("agent", path, body, hdr)
    ok = out.get("status") == 400 and "model-proxy rejected" in out.get("body", "") and len(got) == 0
    rec(tid, "400 from the proxy; the provider receives NOTHING", "PASS" if ok else "FAIL", control=ctl, out=out, provider_requests=len(got),
        request=ev, summary=f"status={out.get('status')} provider_n={len(got)} why={out.get('body', '')[40:120]!r}")
out, got, ev = send("agent", "/v1/messages", "{" + MSG + ',"tools":[' + WS + "]}", gzip=True)
rec("T6k-gzip-encoded-body", "gzip-encoded body rejected (no decompress-then-check differential); provider receives nothing",
    "PASS" if out.get("status") == 400 and len(got) == 0 else "FAIL", control="T1-anthropic-custom-tools", out=out, summary=f"status={out.get('status')}")
out, got, ev = send("agent", "/v1/messages", "{" + MSG + "}", gzip=True)
rec("T6l-gzip-even-if-benign", "gzip is rejected even for a benign body (fail-closed encoding rule)",
    "PASS" if out.get("status") == 400 and len(got) == 0 else "FAIL", control="T1c-client-key-replaced", out=out, summary=f"status={out.get('status')}")

# ---------------- T7 SSE ----------------
out, got, ev = send("agent", "/v1/messages", "{" + MSG + ',"stream":true}', sse=True)
a = out.get("arrivals", [])
rec("T7-sse", "5 SSE events arrive incrementally (~0.6 s apart) through the proxy",
    "PASS" if len(a) == 5 and all(y > x for x, y in zip(a, a[1:])) and a[-1] - a[0] >= 4 * 0.6 * 0.7 else "FAIL", arrivals=a, summary=f"arrivals={a}")

# ---------------- T8 direct provider access from the cell ----------------
probe = ("import socket,json;r={}\n"
         "for h,p in [('mock-provider',9000),('api.anthropic.com',443),('api.openai.com',443)]:\n"
         "  try: socket.create_connection((h,p),4).close(); r[h]='connected'\n"
         "  except Exception as e: r[h]=type(e).__name__+': '+str(e)[:60]\n"
         "print(json.dumps(r))")
n0 = len(plog()); r = run(DC + ["exec", "-T", "agent", "python", "-c", probe]); got = plog()[n0:]
rec("T8-cell-direct-provider", "cell cannot reach the mock provider or real provider hostnames directly",
    "PASS" if "connected" not in r["stdout"] and not got else "FAIL", control="C-provider-observes-direct", stdout=r["stdout"], summary=r["stdout"].strip()[:160])
mpip = json.loads(run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", "s6model-mock-provider-1"])["stdout"])["s6model_provnet"]["IPAddress"]
r = run(DC + ["exec", "-T", "agent", "python", "-c", f"import socket\ntry: socket.create_connection(('{mpip}',9000),4); print('connected')\nexcept Exception as e: print(type(e).__name__, e)"])
rec("T8b-cell-direct-provider-ip", f"cell cannot reach the mock provider by IP {mpip}", "PASS" if "connected" not in r["stdout"] else "FAIL",
    control="C-provider-observes-direct", summary=r["stdout"].strip()[:100])

# ---------------- T9 live provider ----------------
results.append({"id": "T9-live-provider", "expected": "optional live smoke", "verdict": "BLOCKED",
                "note": "requires a human decision and a real provider key; not attempted (see S6 VERDICT)"})
print("T9-live-provider                     BLOCKED       needs API key + decision")

(RUN / "results.jsonl").write_text("\n".join(json.dumps(x) for x in results) + "\n")
c = {}
for x in results:
    c[x["verdict"]] = c.get(x["verdict"], 0) + 1
print("SUMMARY", c)
