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

        # T8b: larger concurrency (200 mixed calls), same expectation
        w0 = writes()
        jobs = [call(c, "write_record", {"x": ("forbidden" if i % 2 else f"k{i}")}) for i in range(200)]
        rs = await asyncio.gather(*jobs)
        delta = sorted(writes()[len(w0):]); expected = sorted(f"k{i}-mod" for i in range(0, 200, 2))
        rec("S1-T8b-200", "exactly the 100 allowed writes; no forbidden write", {"n_delta": len(delta), "forbidden_written": [d for d in delta if "forbidden" in d],
            "missing": sorted(set(expected) - set(delta))[:10], "client_ok": sum(1 for x in rs if x.get("ok"))},
            "PASS" if delta == expected else "FAIL")

        # T4 sweep: canary in ANY backend request (headers or body) during the strict-PEP phase
        leak = [r["path"] for r in backend_reqs() if CANARY in json.dumps(r["headers"]) or CANARY in r["body"]]
        rec("S1-T4-strict-sweep", "canary absent from every backend request (headers and body) via the strict PEP",
            {"n_backend_requests": len(backend_reqs()), "leaks": leak[:5]}, "PASS" if not leak and backend_reqs() else "FAIL")

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

    # T5 strip attempts (PEP clears _meta before forwarding); record whether x-evil still reaches the backend
    for name in ["strip_rc", "strip_msg", "strip_rc_teloff"]:
        url = os.environ.get("URL_" + name.upper())
        if not url: continue
        async with client_for(url) as c:
            t = time.time(); r = await call(c, "echo", meta={"x-evil": "1", "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"})
            seen = tool_calls_seen(t)
            metas = [s["meta"] for s in seen]
            evil = any(m and "x-evil" in m for m in metas)
            rec(f"S1-T5-{name}", "record whether this strip method removes client _meta (x-evil) before the backend",
                {"client": r, "meta_at_backend": metas, "x_evil_reached_backend": evil}, "RECORDED", stripped=bool(seen) and not evil)

    # T10 ordering
    t10 = {}
    for name in ["pep_outer", "pep_inner", "pep_outer_onrequest", "pep_inner_onrequest"]:
        if not os.environ.get("URL_" + name.upper()): continue
        async with client_for(os.environ["URL_" + name.upper()]) as c:
            w0 = writes(); r = await call(c, "write_record", {"x": "forbidden"})
            d1 = writes()[len(w0):]
            w0 = writes(); r2 = await call(c, "write_record", {"x": "z"})
            d2 = writes()[len(w0):]
            rec(f"S1-T10-{name}", "record what backend wrote when a 2nd middleware mutates args",
                {"forbidden_call": r, "forbidden_delta": d1, "allowed_delta": d2}, "RECORDED")
            t10[name] = {"forbidden_delta": d1, "allowed_delta": d2}

    # T10 rule: with the PEP innermost, what reaches the backend is exactly what the PEP checked and
    # rewrote (every write ends with the PEP's "-mod"); with the PEP outer, a later middleware changes
    # arguments after authorization (the TOCTOU gap is reproduced, which is why the rule is needed).
    inner = [k for k in t10 if k.startswith("pep_inner")]; outer = [k for k in t10 if k.startswith("pep_outer")]
    inner_safe = all(all(w.endswith("-mod") for w in t10[k]["forbidden_delta"] + t10[k]["allowed_delta"]) and t10[k]["allowed_delta"] for k in inner)
    outer_gap = all(any(not w.endswith("-mod") for w in t10[k]["forbidden_delta"] + t10[k]["allowed_delta"]) for k in outer)
    rec("S1-T10-rule", "PEP innermost => backend receives only PEP-checked args; PEP outer => post-authorization mutation reproduced",
        {"inner": {k: t10[k] for k in inner}, "outer": {k: t10[k] for k in outer}, "inner_safe": inner_safe, "outer_gap_reproduced": outer_gap},
        "PASS" if inner and outer and inner_safe and outer_gap else "FAIL")

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
