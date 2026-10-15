"""Runs in the `harness` test fixture (testnet -> terminator only). Presents chosen (certificate, token)
combinations directly to the terminator. Usage: python s7_harness.py <cert:a|b|rogue|none> <token-name|none> [json-extra-headers]
Prints raw HTTP status of an unauthenticated-body POST plus the outcome of a full MCP tool call."""
import asyncio, json, ssl, sys, http.client

cert, tname = sys.argv[1], sys.argv[2]
extra = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
T = json.load(open("/secrets/tokens.json"))
def resolve(v):  # "@JWT_X" -> "Bearer <token>"
    return f"Bearer {T[v[1:]]}" if isinstance(v, str) and v.startswith("@") else v
headers = {k: ([resolve(x) for x in v] if isinstance(v, list) else resolve(v)) for k, v in extra.items()}
if tname != "none":
    headers["Authorization"] = f"Bearer {T[tname]}"

ctx = ssl.create_default_context(cafile="/secrets/ca.crt")
if cert != "none":
    ctx.load_cert_chain(f"/secrets/{cert}.crt", f"/secrets/{cert}.key")

res = {"cert": cert, "token": tname, "extra_headers": list(extra)}
try:  # raw request; list-valued extra headers are sent as duplicate header lines
    conn = http.client.HTTPSConnection("terminator", 8443, context=ctx, timeout=10)
    conn.putrequest("POST", "/mcp")
    for k, v in {**headers, "Content-Type": "application/json", "Content-Length": "2"}.items():
        for one in (v if isinstance(v, list) else [v]):
            conn.putheader(k, one)
    conn.endheaders(b"{}")
    r = conn.getresponse(); res["raw_status"] = r.status; res["raw_body"] = r.read()[:200].decode(errors="replace")
except Exception as e:
    res["raw_error"] = f"{type(e).__name__}: {e}"[:200]

RAW_ONLY = any(isinstance(v, list) for v in headers.values())

async def mcp():
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    single = {k: (v[0] if isinstance(v, list) else v) for k, v in headers.items()}
    async with Client(StreamableHttpTransport("https://terminator:8443/mcp", headers=single, verify=ctx)) as c:
        r = await c.call_tool("echo", {}, raise_on_error=False)
        return {"ok": not r.is_error, "texts": [getattr(x, "text", None) for x in r.content or []]}
try:
    res["mcp"] = {"skipped": "duplicate headers: raw request only"} if RAW_ONLY else asyncio.run(mcp())
except Exception as e:
    res["mcp"] = {"ok": False, "exception": f"{type(e).__name__}: {e}"[:300]}
print(json.dumps(res))
