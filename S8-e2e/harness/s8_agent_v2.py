"""S8 v2 scripted agent helpers (NO LLM), run inside agent_a. One JSON object per invocation.
  mcp <json-steps> [json-headers]  : MCP session via the sidecar; steps = [[tool, args], ...]; extra headers optional
  raw <host> <port>                : send raw bytes from STDIN (exactly as given) and return the response bytes
  reach <host> <port>              : TCP connect attempt"""
import asyncio, json, socket, sys

cmd = sys.argv[1]

def out(d):
    print(json.dumps(d)); sys.exit(0)

if cmd == "mcp":
    steps = json.loads(sys.argv[2]); hdrs = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    async def go():
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        res = []
        async with Client(StreamableHttpTransport("http://127.0.0.1:8081/mcp", headers=hdrs)) as c:
            for name, args in steps:
                r = await c.call_tool(name, args, raise_on_error=False)
                res.append({"tool": name, "is_error": r.is_error, "text": [getattr(x, "text", "") for x in r.content or []]})
        return res
    try:
        out({"cmd": cmd, "results": asyncio.run(go())})
    except Exception as e:
        out({"cmd": cmd, "exception": f"{type(e).__name__}: {e}"[:300]})

if cmd == "raw":
    data = sys.stdin.buffer.read()
    try:
        s = socket.create_connection((sys.argv[2], int(sys.argv[3])), 5); s.sendall(data); s.settimeout(6); buf = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        out({"cmd": cmd, "response": buf.decode("utf-8", "replace")[:1500]})
    except Exception as e:
        out({"cmd": cmd, "error": f"{type(e).__name__}: {e}"[:200]})

if cmd == "reach":
    try:
        socket.create_connection((sys.argv[2], int(sys.argv[3])), 4).close(); out({"cmd": cmd, "reached": True})
    except Exception as e:
        out({"cmd": cmd, "reached": False, "error": f"{type(e).__name__}: {e}"[:120]})
out({"error": "unknown cmd"})
