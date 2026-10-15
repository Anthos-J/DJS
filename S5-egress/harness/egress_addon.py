"""S5 egress PEP addon for mitmproxy 12.2.3 (AM4: destination-level decisions, no TLS interception).
Decisions happen in hooks that run BEFORE any upstream contact (connection_strategy=lazy):
  http_connect  -> CONNECT: session auth (407) + destination allowlist (403)
  request       -> plain-HTTP absolute-form and redirect hops: auth, allowlist, per-session byte budget
  server_connect-> defence in depth: refuse any upstream connection to a host not on the allowlist
Session identity = Proxy-Authorization Basic <session>:<token>; recorded on every decision."""
import base64, json, os, time
from mitmproxy import http

ALLOW = {"allowed-srv"}
SESSIONS = {"sess-1": "tok-good-1"}
BUDGET = int(os.environ.get("BYTE_BUDGET", "3000000"))
LOG = os.environ.get("EGRESS_LOG", "/log/egress.jsonl")
used = {}

def log(**e):
    e["t"] = time.time()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(e) + "\n")

def norm(h):
    return (h or "").strip().lower().rstrip(".")

def session(flow):
    h = flow.request.headers.get("Proxy-Authorization", "")
    if not h.startswith("Basic "):
        return None
    try:
        u, p = base64.b64decode(h[6:]).decode().split(":", 1)
    except Exception:
        return None
    return u if SESSIONS.get(u) == p else None

def deny(flow, code, why, sess=None):
    hdrs = {"Proxy-Authenticate": 'Basic realm="egress"'} if code == 407 else {}
    flow.response = http.Response.make(code, f"egress: {why}\n".encode(), hdrs)
    log(ev="deny", code=code, why=why, method=flow.request.method, host=flow.request.host, port=flow.request.port, sess=sess)

def http_connect(flow: http.HTTPFlow):
    s = session(flow)
    if not s:
        return deny(flow, 407, "proxy auth required")
    if norm(flow.request.host) not in ALLOW:
        return deny(flow, 403, "destination not allowed", s)
    log(ev="allow-connect", host=flow.request.host, port=flow.request.port, sess=s)

def request(flow: http.HTTPFlow):
    if flow.request.method == "CONNECT":
        return
    s = session(flow)
    if not s:
        return deny(flow, 407, "proxy auth required")
    if norm(flow.request.host) not in ALLOW:
        return deny(flow, 403, "destination not allowed", s)
    n = len(flow.request.raw_content or b"")
    if used.get(s, 0) + n > BUDGET:
        return deny(flow, 403, "byte budget exceeded", s)
    used[s] = used.get(s, 0) + n
    flow.request.headers.pop("Proxy-Authorization", None)
    log(ev="allow", method=flow.request.method, host=flow.request.host, path=flow.request.path, bytes=n, used=used[s], sess=s)

def responseheaders(flow: http.HTTPFlow):
    flow.response.stream = True  # SSE / incremental delivery

def server_connect(data):
    host = norm(data.server.address[0] if data.server.address else "")
    if host not in ALLOW:
        data.server.error = "egress: upstream connection refused by policy"
        log(ev="deny-server-connect", host=host)
