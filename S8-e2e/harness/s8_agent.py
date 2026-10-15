"""Scripted agent (NO LLM) for S8, runs inside agent_a (cell A). Every step goes through a mediated path:
MCP via the sidecar (127.0.0.1:8081), model calls via model-proxy:8080. Prints one JSON line per step."""
import asyncio, http.client, json

async def mcp_steps():
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    out = []
    async with Client(StreamableHttpTransport("http://127.0.0.1:8081/mcp")) as c:
        tools = await c.list_tools()
        out.append({"step": "list_tools", "tools": sorted(t.name for t in tools)})
        for name, args in [("read_doc", {}), ("read_hr", {}), ("send_report", {"to": "partner@external.example"}), ("drop_tables", {})]:
            r = await c.call_tool(name, args, raise_on_error=False)
            out.append({"step": f"call:{name}", "is_error": r.is_error, "text": [getattr(x, "text", "") for x in r.content or []]})
    return out

def model(body):
    c = http.client.HTTPConnection("model-proxy", 8080, timeout=15)
    raw = json.dumps(body).encode()
    c.request("POST", "/v1/messages", body=raw, headers={"Content-Type": "application/json", "Content-Length": str(len(raw))})
    r = c.getresponse(); return {"status": r.status, "body": r.read().decode()[:200]}

steps = asyncio.run(mcp_steps())
base = {"model": "m", "max_tokens": 16, "messages": [{"role": "user", "content": "summarise"}]}
steps.append({"step": "model:allowed", **model(base)})
steps.append({"step": "model:server_tool", **model({**base, "tools": [{"type": "web_search_20260209", "name": "web_search"}]})})
for s in steps:
    print(json.dumps(s))
