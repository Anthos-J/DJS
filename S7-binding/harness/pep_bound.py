"""S7 PEP: the S1 FastMCP proxy PEP (allowlist, AM1 forward_incoming_headers=False, PEP innermost)
wrapped in an ASGI credential-binding check (AM2 / G5):
  - exactly one X-Client-Cert (set by the terminator from $ssl_client_escaped_cert) and exactly one
    Authorization: Bearer <JWT>, else 401;
  - JWT: ES256 signature by the gateway issuer key, iss/aud/exp/sid/cnf required, sid not revoked;
  - cnf.x5t#S256 must equal base64url(SHA-256(DER(presented cert))), and the cert must chain to the test CA;
  - identity = JWT `sub`, taken only from a verified, bound token (never from other request headers).
Every HTTP request is checked before the MCP layer sees it (no unauthenticated initialize / list / call)."""
import base64, contextvars, hashlib, json, os, time
from urllib.parse import unquote
import jwt, uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError

SEC = os.environ.get("PEP_SECRETS", "/secrets")
LOG = os.environ.get("PEP_LOG", "/log/pep.jsonl")
BACKEND = os.environ.get("BACKEND", "http://backend:9000/mcp")
ISSUER_PUB = serialization.load_pem_public_key(open(f"{SEC}/issuer_pub.pem", "rb").read())
CA = x509.load_pem_x509_certificate(open(f"{SEC}/ca.crt", "rb").read())
ALLOWED = {"read_doc", "write_record", "echo", "slow_stream"}
IDENTITY = contextvars.ContextVar("identity", default=None)

def log(ev):
    ev["t"] = time.time()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(ev) + "\n")

def revoked():
    try:
        return {l.strip() for l in open(f"{SEC}/revoked.txt") if l.strip()}
    except FileNotFoundError:
        return set()

def check_binding(headers):
    certs = [v for k, v in headers if k == "x-client-cert"]
    auths = [v for k, v in headers if k == "authorization"]
    if len(certs) != 1:
        return None, f"expected exactly 1 X-Client-Cert, got {len(certs)}", {}
    if len(auths) != 1 or not auths[0].startswith("Bearer "):
        return None, f"expected exactly 1 Bearer Authorization, got {len(auths)}", {}
    try:
        c = x509.load_pem_x509_certificate(unquote(certs[0]).encode())
    except Exception as e:
        return None, f"unparseable client cert: {type(e).__name__}", {}
    try:  # defence in depth: the terminator already verified the chain
        CA.public_key().verify(c.signature, c.tbs_certificate_bytes, ec.ECDSA(c.signature_hash_algorithm))
    except Exception:
        return None, "client cert not issued by the test CA", {}
    thumb = base64.urlsafe_b64encode(hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).digest()).rstrip(b"=").decode()
    info = {"cert_cn": c.subject.rfc4514_string(), "cert_x5t": thumb}
    try:
        cl = jwt.decode(auths[0][7:], ISSUER_PUB, algorithms=["ES256"], audience="mandate-pep", issuer="mandate-gw",
                        options={"require": ["exp", "iat", "sub", "sid", "iss", "aud", "cnf"]})
    except jwt.PyJWTError as e:
        return None, f"jwt rejected: {type(e).__name__}: {e}", info
    info.update({"sub": cl["sub"], "sid": cl["sid"]})
    if cl["sid"] in revoked():
        return None, "session revoked", info
    want = (cl.get("cnf") or {}).get("x5t#S256")
    if want != thumb:
        return None, f"cnf mismatch: token bound to {want}, presented {thumb}", info
    return cl["sub"], "binding match", info

class SpikePEP(Middleware):  # same allowlist logic as S1; added last (innermost) per AM8
    async def on_call_tool(self, context, call_next):
        name = context.message.name
        log({"phase": "tool-pre", "identity": IDENTITY.get(), "name": name})
        if name not in ALLOWED:
            raise ToolError("DENY: tool not allowlisted")
        return await call_next(context)

proxy = create_proxy(ProxyClient(StreamableHttpTransport(BACKEND), forward_incoming_headers=False), name="pep-s7")
proxy.add_middleware(SpikePEP())
inner = proxy.http_app()

async def app(scope, receive, send):
    if scope["type"] != "http":
        return await inner(scope, receive, send)
    headers = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in scope["headers"]]
    ident, why, info = check_binding(headers)
    log({"phase": "binding", "path": scope["path"], "method": scope["method"], "ok": ident is not None, "why": why, **info,
         "client_ip": (scope.get("client") or ["?"])[0]})
    if ident is None:
        body = json.dumps({"error": "credential binding failed", "why": why}).encode()
        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
        return
    tok = IDENTITY.set(ident)
    try:
        return await inner(scope, receive, send)
    finally:
        IDENTITY.reset(tok)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, lifespan="on")
