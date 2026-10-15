"""S7 tool backend (FastMCP). Records every raw HTTP request (headers + body) so downstream credential
confinement can be checked: the agent's JWT and certificate must never arrive here. Holds a dummy
downstream tool secret (TOOL_API_KEY) that must never be visible inside an agent container."""
import asyncio, json, os, time
import uvicorn
from fastmcp import FastMCP, Context

LOG = os.environ.get("BACKEND_LOG", "/log/backend_requests.jsonl")
TOOL_API_KEY = os.environ.get("TOOL_API_KEY", "")  # dummy downstream secret; used only server-side
mcp = FastMCP("backend-s7")

@mcp.tool
def read_doc() -> str:
    return "doc-text"

@mcp.tool
def echo() -> str:
    return "echo-ok"

@mcp.tool
async def slow_stream(n: int = 5, delay: float = 0.6, ctx: Context = None) -> str:
    for i in range(n):
        await ctx.report_progress(progress=i + 1, total=n, message=f"step {i + 1}")
        await asyncio.sleep(delay)
    return f"streamed {n}"

inner = mcp.http_app()

async def app(scope, receive, send):
    if scope["type"] == "http":
        msgs, body = [], b""
        while True:
            m = await receive(); msgs.append(m); body += m.get("body", b"")
            if not m.get("more_body"):
                break
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "path": scope["path"],
                                "headers": {k.decode(): v.decode() for k, v in scope["headers"]},
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
