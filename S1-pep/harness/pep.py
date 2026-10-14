"""S1 PEP: FastMCP 4.1 proxy + spike middleware. Env:
FWD=true|false|default (forward_incoming_headers), ORDER=pep_only|pep_outer|pep_inner."""
import json, os, time
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

BACKEND = os.environ.get("BACKEND", "http://backend:9000/mcp")
FWD = os.environ.get("FWD", "false")
ORDER = os.environ.get("ORDER", "pep_only")
LOG = os.environ.get("DATA", "/data") + f"/pep_{os.environ.get('PEP_NAME','pep')}.jsonl"
ALLOWED = {"read_doc", "write_record", "echo"}

def log(ev):
    ev["t"] = time.time()
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")

class SpikePEP(Middleware):
    async def on_call_tool(self, context, call_next):
        name = context.message.name
        args = dict(context.message.arguments or {})
        log({"phase": "pre", "name": name, "args": args})
        if name not in ALLOWED:
            log({"phase": "deny", "name": name, "why": "not-allowlisted"})
            raise ToolError("DENY: tool not allowlisted")
        if name == "write_record" and args.get("x") == "forbidden":
            log({"phase": "deny", "name": name, "why": "policy"})
            raise ToolError("DENY: policy")
        if name == "write_record":
            context.message.arguments = {**args, "x": args["x"] + "-mod"}
        result = await call_next(context)
        log({"phase": "post", "name": name})
        try:
            result.content = list(result.content) + [TextContent(type="text", text="[PEP-MARK]")]
        except Exception as e:  # record if result is not mutable this way
            log({"phase": "mark-failed", "err": repr(e)})
        return result

class Mutator(Middleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name == "write_record":
            a = dict(context.message.arguments or {})
            context.message.arguments = {**a, "x": "MUTATED-AFTER-CHECK"}
        return await call_next(context)

transport = StreamableHttpTransport(BACKEND)
if FWD == "default":
    client = ProxyClient(transport)
else:
    client = ProxyClient(transport, forward_incoming_headers=(FWD == "true"))
proxy = create_proxy(client, name="pep")
if ORDER == "pep_only":
    proxy.add_middleware(SpikePEP())
elif ORDER == "pep_outer":
    proxy.add_middleware(SpikePEP()); proxy.add_middleware(Mutator())
elif ORDER == "pep_inner":
    proxy.add_middleware(Mutator()); proxy.add_middleware(SpikePEP())

if __name__ == "__main__":
    proxy.run(transport="http", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
