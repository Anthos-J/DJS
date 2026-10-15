"""S8 tool server. Every tool logs an EFFECT record (with time) when it executes: the independent observation
for G0 ('every effect is preceded by a PEP decision'). Raw requests are logged too (credential leak check)."""
import json, os, time
import uvicorn
from fastmcp import FastMCP, Context

EFF = "/log/effects.jsonl"; REQ = "/log/backend_requests.jsonl"
mcp = FastMCP("backend-s8")

def decision_id(ctx):
    try:
        m = ctx.request_context.meta
        d = m if isinstance(m, dict) else (m.model_dump() if hasattr(m, "model_dump") else {})
        return (d or {}).get("mandate_decision_id")
    except Exception:
        return None

def effect(tool, **kw):
    os.makedirs("/log", exist_ok=True)
    with open(EFF, "a") as f:
        f.write(json.dumps({"t": time.time(), "tool": tool, **kw}) + "\n")

@mcp.tool
def read_doc(ctx: Context) -> str:
    effect("read_doc", decision_id=decision_id(ctx)); return "quarterly figures (conf 2)"

@mcp.tool
def read_hr(ctx: Context) -> str:
    effect("read_hr", decision_id=decision_id(ctx)); return "HR RECORDS"

@mcp.tool
def send_report(to: str, ctx: Context) -> str:
    effect("send_report", to=to, decision_id=decision_id(ctx)); return f"sent to {to}"

inner = mcp.http_app()

async def app(scope, receive, send):
    if scope["type"] == "http":
        msgs, body = [], b""
        while True:
            m = await receive(); msgs.append(m); body += m.get("body", b"")
            if not m.get("more_body"):
                break
        os.makedirs("/log", exist_ok=True)
        with open(REQ, "a") as f:
            f.write(json.dumps({"t": time.time(), "headers": {k.decode(): v.decode() for k, v in scope["headers"]},
                                "body": body.decode(errors="replace")}) + "\n")
        it = iter(msgs)
        async def replay():
            try:
                return next(it)
            except StopIteration:
                return await receive()
        return await inner(scope, replay, send)
    return await inner(scope, receive, send)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000, lifespan="on")
