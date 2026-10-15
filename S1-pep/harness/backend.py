"""S1 backend: FastMCP server wrapped in an ASGI logger that records every raw HTTP request
(headers + body) it receives -> independent observation for the PEP tests."""
import json, os, time, threading
_LOCK = threading.Lock()
import uvicorn
from fastmcp import FastMCP

import pathlib
DATA = os.environ.get("DATA", "/data")
LOG = os.path.join(DATA, "backend_requests.jsonl")
mcp = FastMCP("backend")

@mcp.tool
def read_doc() -> str:
    return "doc-text"

@mcp.tool
def write_record(x: str) -> str:
    with _LOCK, open(os.path.join(DATA, "writes.log"), "a") as f:
        f.write(x + "\n")
    return f"wrote {x}"

@mcp.tool
def echo() -> str:
    return "echo-ok"

inner = mcp.http_app()

async def app(scope, receive, send):
    if scope["type"] == "http":
        body = b""
        msgs = []
        while True:
            m = await receive()
            msgs.append(m)
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        hdrs = {k.decode(): v.decode() for k, v in scope["headers"]}
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "path": scope["path"], "headers": hdrs,
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
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "9000")), lifespan="on")
