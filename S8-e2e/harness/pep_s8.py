"""S8 PEP = S7 credential binding (imported from S7's pep_bound) + S1 proxy (FWD=false, PEP innermost)
+ S2 policy P via two-pass Cedar (AM9: Allow only with no errors). A decision record is written BEFORE the
call is forwarded; APPROVAL_REQUIRED returns 'pending' and never reaches the backend. Spike harness only."""
import copy, json, os, sys, time, uuid
sys.path.insert(0, "/s7h")
os.environ.setdefault("BACKEND", "http://backend:9000/mcp")
import pep_bound as pb                      # binding check, identity contextvar, logging
import uvicorn
from cedarpy import is_authorized, Decision, PolicySet, Schema
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError

P = PolicySet.from_str(open("/s2cfg/policies_P.cedar").read())
SCH = Schema.from_str(open("/s2cfg/schema.cedarschema").read())
# tool -> (cedar action, resource, target) ; session labels for this scripted session are fixed (no untrusted reads)
TOOLS = {
    "read_doc": ("read", 'Resource::"doc"', {"external": False, "clearance": 3}),
    "read_hr": ("read", 'Resource::"hr_records"', {"external": False, "clearance": 3}),
    "send_report": ("send", 'Sink::"ext_email"', {"external": True, "clearance": 0}),
}
SESSION = {"conf": 2, "integ": 2}            # session has read conf-2 data (read_doc is classed conf 2 here)

def two_pass(action, resource, target):
    def ev(approved):
        ctx = {"session": dict(SESSION), "target": {**target, "untrusted_threshold": 1}, "params": {"all_grounded": True}, "approved": approved}
        return is_authorized({"principal": 'Agent::"procurement"', "action": f'Action::"{action}"', "resource": resource, "context": ctx}, P, [], schema=SCH)
    r1 = ev(True)
    if r1.diagnostics.errors or r1.decision != Decision.Allow:
        return "DENY"
    r2 = ev(False)
    if r2.diagnostics.errors:
        return "DENY"
    return "PERMIT" if r2.decision == Decision.Allow else "APPROVAL_REQUIRED"

class DecisionPEP(Middleware):
    async def on_call_tool(self, context, call_next):
        name = context.message.name
        dec = two_pass(*TOOLS[name]) if name in TOOLS else "DENY"
        rid = uuid.uuid4().hex[:12]
        pb.log({"phase": "decision", "rid": rid, "identity": pb.IDENTITY.get(), "tool": name, "decision": dec,
                "why": "not allowlisted" if name not in TOOLS else "cedar two-pass"})
        if dec == "DENY":
            raise ToolError(f"DENY ({rid})")
        if dec == "APPROVAL_REQUIRED":
            raise ToolError(f"APPROVAL_REQUIRED: pending approval {rid}; not executed")
        # Correlation (Wave 6): attach THIS decision's id to the forwarded request (_meta is forwarded to the backend,
        # S1-T5). Overwrites any client-supplied value, so an agent cannot borrow another decision's id.
        rc = context.fastmcp_context.request_context if context.fastmcp_context else None
        try:
            if rc is not None and isinstance(rc.meta, dict):
                rc.meta["mandate_decision_id"] = rid
            elif rc is not None:
                object.__setattr__(rc, "meta", {**(dict(rc.meta) if rc.meta else {}), "mandate_decision_id": rid})
        except Exception as e:
            pb.log({"phase": "correlation-failed", "rid": rid, "err": repr(e)})
        return await call_next(context)

proxy = create_proxy(ProxyClient(StreamableHttpTransport(os.environ["BACKEND"]), forward_incoming_headers=False), name="pep-s8")
proxy.add_middleware(DecisionPEP())          # only (and therefore innermost) tool-call middleware: AM8
inner = proxy.http_app()

async def app(scope, receive, send):
    if scope["type"] != "http":
        return await inner(scope, receive, send)
    headers = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in scope["headers"]]
    ident, why, info = pb.check_binding(headers)
    pb.log({"phase": "binding", "ok": ident is not None, "why": why, **info})
    if ident is None:
        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps({"error": "binding failed", "why": why}).encode()})
        return
    tok = pb.IDENTITY.set(ident)
    try:
        return await inner(scope, receive, send)
    finally:
        pb.IDENTITY.reset(tok)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, lifespan="on")
