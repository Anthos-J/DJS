"""S1 PEP: FastMCP 4.1 proxy + spike middleware. Env:
FWD=true|false|default (forward_incoming_headers), ORDER=pep_only|pep_outer|pep_inner|pep_outer_onrequest,
STRIP_META=none|request_context|message (T5 strip attempts), HOST (bind address)."""
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
STRIP_META = os.environ.get("STRIP_META", "none")
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
        if STRIP_META == "request_context":
            # The proxy forwards ctx.request_context.meta (fastmcp/server/providers/proxy.py _forwardable_request_meta)
            rc = context.fastmcp_context.request_context if context.fastmcp_context else None
            before = None if rc is None else (dict(rc.meta) if isinstance(rc.meta, dict) else repr(rc.meta))
            try:
                if rc is not None and isinstance(rc.meta, dict):
                    rc.meta.clear()
                elif rc is not None and rc.meta is not None:
                    object.__setattr__(rc, "meta", None)
                log({"phase": "strip", "how": "request_context", "before": before})
            except Exception as e:
                log({"phase": "strip-failed", "how": "request_context", "err": repr(e)})
        elif STRIP_META == "message":
            try:
                context.message.meta = None
                log({"phase": "strip", "how": "message"})
            except Exception as e:
                log({"phase": "strip-failed", "how": "message", "err": repr(e)})
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

class RequestMutator(Middleware):
    """Generic on_request hook (not tool-specific), to test whether a non-tool middleware
    added after the PEP can still change arguments after authorization (T10c)."""
    async def on_request(self, context, call_next):
        m = context.message
        if getattr(m, "name", None) == "write_record":
            a = dict(getattr(m, "arguments", None) or {})
            m.arguments = {**a, "x": "MUTATED-BY-ON_REQUEST"}
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
elif ORDER == "pep_outer_onrequest":
    proxy.add_middleware(SpikePEP()); proxy.add_middleware(RequestMutator())
elif ORDER == "pep_inner_onrequest":
    proxy.add_middleware(RequestMutator()); proxy.add_middleware(SpikePEP())

import fastmcp as _f
log({"phase": "startup", "fastmcp": _f.__version__, "telemetry_mode": str(_f.settings.telemetry_mode), "FWD": FWD, "ORDER": ORDER, "STRIP_META": STRIP_META})

if __name__ == "__main__":
    proxy.run(transport="http", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
