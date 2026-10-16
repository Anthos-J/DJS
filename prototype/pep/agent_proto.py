"""Scripted agent (NO LLM) inside a cell. Usage: python agent_proto.py '<json list of [tool, args]>'
Calls tools through the cell sidecar (mTLS + bound JWT added by the sidecar); prints one JSON object."""
import asyncio, json, sys


async def go(steps):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    out = []
    async with Client(StreamableHttpTransport("http://127.0.0.1:8081/mcp")) as c:
        for tool, args in steps:
            r = await c.call_tool(tool, args, raise_on_error=False)
            out.append({"tool": tool, "ok": not r.is_error, "text": " ".join(getattr(x, "text", "") for x in r.content or [])[:300]})
    return out

try:
    print(json.dumps({"results": asyncio.run(go(json.loads(sys.argv[1])))}))
except Exception as e:
    print(json.dumps({"exception": f"{type(e).__name__}: {e}"[:300]}))
