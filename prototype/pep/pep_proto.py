"""MANDATE prototype PEP = S7 credential binding (imported from S7's pep_bound: mTLS cert + bound JWT -> identity)
+ S1 proxy (forward_incoming_headers=False; this is the only, hence innermost, tool-call middleware: AM8)
+ control-plane decision (drift engine incl. frozen policy P) for EVERY tool call. Fail closed if the control plane
is unreachable or answers anything but ALLOW. Each forwarded call carries the control decision id in _meta, so the
backend's effect log can be correlated (independent observation, S8 v2 method)."""
import asyncio, json, os, sys, urllib.request
sys.path.insert(0, "/s7h")
os.environ.setdefault("BACKEND", "http://backend:9000/mcp")
import pep_bound as pb
import uvicorn
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError

CONTROL = os.environ.get("CONTROL_URL", "http://control:8800/api/decide")
TOKEN = os.environ.get("MANDATE_PEP_TOKEN", "demo-pep-token")
PEP_ONLY = {"_delegation", "_approval"}   # PEP-level arguments; never forwarded to tool servers


OBSERVE = CONTROL.rsplit("/api/", 1)[0] + "/api/observe"
MAX_SCAN_CHARS = 200_000   # longer results are reported as truncated; E4.3.1 then treats them as unverified (taint)


def report_content(ev):
    req = urllib.request.Request(OBSERVE, data=json.dumps(ev).encode(), headers={"Content-Type": "application/json", "X-PEP-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def ask_control(ev):
    req = urllib.request.Request(CONTROL, data=json.dumps(ev).encode(), headers={"Content-Type": "application/json", "X-PEP-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class ControlPEP(Middleware):
    async def on_call_tool(self, context, call_next):
        name = context.message.name
        args = dict(context.message.arguments or {})
        ident = pb.IDENTITY.get()
        ev = {"agent_id": ident, "tool": name, "args": {k: v for k, v in args.items() if k not in PEP_ONLY},
              "destination": args.get("destination") or "internal", "credential_valid": ident is not None,
              "delegation_id": args.get("_delegation"), "approval_id": args.get("_approval")}
        try:
            d = await asyncio.to_thread(ask_control, ev)
        except Exception as e:
            pb.log({"phase": "control-unreachable", "tool": name, "identity": ident, "err": repr(e)[:200]})
            raise ToolError("DENY: control plane unreachable (fail closed)")
        pb.log({"phase": "decision", "rid": d.get("decision_id"), "identity": ident, "tool": name, "decision": d.get("response"),
                "risk": d.get("risk_score"), "why": d.get("reason")})
        if d.get("response") == "APPROVAL_REQUIRED":
            raise ToolError(f"APPROVAL_REQUIRED: {d.get('approval_id')} pending owner approval ({d.get('reason')})")
        if d.get("response") != "ALLOW":
            raise ToolError(f"DENY: {d.get('reason')} (risk {d.get('risk_score')})")
        context.message.arguments = {k: v for k, v in args.items() if k not in PEP_ONLY}
        rc = context.fastmcp_context.request_context if context.fastmcp_context else None
        try:
            if rc is not None and isinstance(rc.meta, dict):
                rc.meta["mandate_decision_id"] = d["decision_id"]
            elif rc is not None:
                object.__setattr__(rc, "meta", {**(dict(rc.meta) if rc.meta else {}), "mandate_decision_id": d["decision_id"]})
        except Exception as e:
            pb.log({"phase": "correlation-failed", "err": repr(e)})
        result = await call_next(context)
        text = " ".join(getattr(x, "text", "") or "" for x in (getattr(result, "content", None) or []))
        try:   # post-execution content scan, before the agent sees the result
            s = await asyncio.to_thread(report_content, {"agent_id": ident, "tool": name, "decision_id": d.get("decision_id"),
                                                         "text": text[:MAX_SCAN_CHARS], "truncated": len(text) > MAX_SCAN_CHARS})
        except Exception as e:
            pb.log({"phase": "observe-unreachable", "tool": name, "identity": ident, "err": repr(e)[:200]})
            raise ToolError("DENY: content could not be checked (fail closed)")
        if s.get("scanned"):
            pb.log({"phase": "content-scan", "rid": d.get("decision_id"), "tool": name, "flagged": s.get("flagged"), "score": s.get("score")})
        return result


proxy = create_proxy(ProxyClient(StreamableHttpTransport(os.environ["BACKEND"]), forward_incoming_headers=False), name="pep-proto")
proxy.add_middleware(ControlPEP())
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
