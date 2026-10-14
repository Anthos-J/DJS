"""S1 client-side tests. Spike code only. Usage: python client_tests.py <out_dir>"""
import asyncio, inspect, json, sys, time, statistics
from pathlib import Path
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CANARY = "CANARY-AUTH-7f3a"
import os
DATA = Path(os.environ.get("DATA", "/data"))
results = []

def rec(tid, expected, observed, verdict, **kw):
    r = {"id": tid, "expected": expected, "observed": observed, "verdict": verdict, **kw}
    results.append(r); print(json.dumps(r)[:600], flush=True)

def backend_reqs():
    p = DATA / "backend_requests.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

def writes():
    p = DATA / "writes.log"
    return p.read_text().splitlines() if p.exists() else []

def tool_calls_seen(since):
    out = []
    for r in backend_reqs():
        if r["t"] < since: continue
        try:
            b = json.loads(r["body"])
        except Exception:
            continue
        if isinstance(b, dict) and b.get("method") == "tools/call":
            out.append({"name": b["params"]["name"], "args": b["params"].get("arguments"),
                        "meta": b["params"].get("_meta"), "headers": r["headers"]})
    return out

def client_for(url, **kw):
    return Client(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {CANARY}"}), **kw)

async def call(c, name, args=None, meta=None):
    kw = {}
    if meta is not None and "meta" in inspect.signature(c.call_tool).parameters:
        kw["meta"] = meta
    try:
        r = await c.call_tool(name, args or {}, raise_on_error=False, **kw) if "raise_on_error" in inspect.signature(c.call_tool).parameters else await c.call_tool(name, args or {}, **kw)
        texts = [getattr(x, "text", None) for x in (r.content or [])]
        return {"ok": not getattr(r, "is_error", False), "is_error": getattr(r, "is_error", None), "texts": texts}
    except Exception as e:
        return {"ok": False, "exception": f"{type(e).__name__}: {e}"[:300]}

async def main():
    strict, default = os.environ["URL_STRICT"], os.environ["URL_DEFAULT"]
    sig = str(inspect.signature(Client.__init__)); rec("S1-ENV", "record Client signature", sig[:500], "RECORDED")

    async with client_for(strict) as c:
        t = time.time(); r = await call(c, "read_doc")
        seen = tool_calls_seen(t)
        rec("S1-T1", "marker in result; backend saw read_doc", {"client": r, "backend_calls": [s["name"] for s in seen]},
            "PASS" if r.get("ok") and "[PEP-MARK]" in (r.get("texts") or []) and any(s["name"] == "read_doc" for s in seen) else "FAIL")

        w0 = writes(); t = time.time(); r = await call(c, "write_record", {"x": "forbidden"})
        seen = tool_calls_seen(t)
        rec("S1-T2", "blocked; writes.log unchanged; backend saw no write_record",
            {"client": r, "writes_delta": writes()[len(w0):], "backend_calls": [s["name"] for s in seen]},
            "PASS" if (not r.get("ok")) and writes() == w0 and not any(s["name"] == "write_record" for s in seen) else "FAIL")

        w0 = writes(); r = await call(c, "write_record", {"x": "a"})
        rec("S1-T3", "backend wrote 'a-mod'", {"client": r, "writes_delta": writes()[len(w0):]},
            "PASS" if writes()[len(w0):] == ["a-mod"] else "FAIL")

        t = time.time(); r = await call(c, "echo", meta={"x-evil": "1", "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"})
        seen = tool_calls_seen(t)
        auth_seen = [s["headers"].get("authorization") for s in seen]
        rec("S1-T4-strict", "forward_incoming_headers=False: backend never sees canary",
            {"backend_authorization_headers": auth_seen},
            "PASS" if seen and not any(a and CANARY in a for a in auth_seen) else "FAIL")
        # any canary anywhere in backend traffic since start?
        leak_any = [r["path"] for r in backend_reqs() if CANARY in json.dumps(r["headers"])]
        rec("S1-T5-meta", "record _meta reaching backend (strict PEP, no stripping)",
            {"meta_at_backend": [s["meta"] for s in seen]}, "RECORDED")

        t = time.time(); outs = {}
        for alias in ["READ_DOC", "read_doc ", "Read_Doc", "backend_read_doc", "0123abcd_read_doc", "read_doc​", "write_record\u0000"]:
            outs[repr(alias)] = await call(c, alias, {"x": "alias"} if "write" in alias else {})
        seen = tool_calls_seen(t)
        rec("S1-T6", "no backend call for any alias", {"client": outs, "backend_calls": [s["name"] for s in seen]},
            "PASS" if not seen else "FAIL")

        # T8 concurrency: 20 mixed calls
        w0 = writes(); t = time.time()
        jobs = [call(c, "write_record", {"x": ("forbidden" if i % 2 else f"c{i}")}) for i in range(20)]
        rs = await asyncio.gather(*jobs)
        delta = sorted(writes()[len(w0):]); expected = sorted(f"c{i}-mod" for i in range(0, 20, 2))
        rec("S1-T8", "exactly the 10 allowed writes", {"delta": delta, "client_ok": sum(1 for x in rs if x.get("ok"))},
            "PASS" if delta == expected else "FAIL")

        r = await call(c, "write_record", {"x": "forbidden"})
        rec("S1-T9", "record client-visible form of a blocked call", r, "RECORDED")

        # T11 latency via PEP
        lat = []
        for _ in range(100):
            s = time.perf_counter(); await call(c, "echo"); lat.append((time.perf_counter() - s) * 1000)
        rec("S1-T11-pep", "record latency (ms)", {"p50": round(statistics.median(lat), 2), "p99": round(sorted(lat)[98], 2)}, "RECORDED")

    # positive control: default forwarding leaks the canary
    async with client_for(default) as c:
        t = time.time(); r = await call(c, "echo")
        seen = tool_calls_seen(t)
        auth_seen = [s["headers"].get("authorization") for s in seen]
        rec("S1-T4-control", "default config forwards canary (positive control)", {"backend_authorization_headers": auth_seen},
            "PASS" if any(a and CANARY in a for a in auth_seen) else "FAIL")

    # direct backend latency baseline
    async with client_for(os.environ["URL_BACKEND"]) as c:
        lat = []
        for _ in range(100):
            s = time.perf_counter(); await call(c, "echo"); lat.append((time.perf_counter() - s) * 1000)
        rec("S1-T11-direct", "record latency (ms)", {"p50": round(statistics.median(lat), 2), "p99": round(sorted(lat)[98], 2)}, "RECORDED")

    # T10 ordering
    for name in ["pep_outer", "pep_inner"]:
        async with client_for(os.environ["URL_" + name.upper()]) as c:
            w0 = writes(); r = await call(c, "write_record", {"x": "forbidden"})
            d1 = writes()[len(w0):]
            w0 = writes(); r2 = await call(c, "write_record", {"x": "z"})
            d2 = writes()[len(w0):]
            rec(f"S1-T10-{name}", "record what backend wrote when a 2nd middleware mutates args",
                {"forbidden_call": r, "forbidden_delta": d1, "allowed_delta": d2}, "RECORDED")

    # T7 protocol eras
    for mode in ["legacy", "auto"]:
        try:
            async with client_for(strict, mode=mode) as c:
                w0 = writes(); r1 = await call(c, "write_record", {"x": "forbidden"}); d1 = writes()[len(w0):]
                w0 = writes(); r2 = await call(c, "write_record", {"x": f"era-{mode}"}); d2 = writes()[len(w0):]
                ok = (not r1.get("ok")) and d1 == [] and d2 == [f"era-{mode}-mod"]
                rec(f"S1-T7-{mode}", "same enforcement in this protocol era", {"blocked": r1, "d1": d1, "d2": d2}, "PASS" if ok else "FAIL")
        except Exception as e:
            rec(f"S1-T7-{mode}", "same enforcement in this protocol era", f"{type(e).__name__}: {e}"[:300], "ERROR")

    (OUT / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
    print("SUMMARY", {r["id"]: r["verdict"] for r in results})

asyncio.run(main())
