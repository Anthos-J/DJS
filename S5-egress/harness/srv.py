"""S5 observed server (allowed-srv / denied-srv). Logs EVERY TCP accept and UDP datagram before handling,
so 'zero contact' can be judged at the destination. HTTP :80, HTTPS :443 (self-signed), UDP :443 and :9999.
Paths: /  ->  'hello from NAME';  /redirect -> 302 http://denied-srv/;  /sse -> 5 events 0.6 s apart;  POST -> 200."""
import datetime as dt, json, os, socket, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAME = os.environ["SRV_NAME"]; LOG = f"/log/{NAME}.jsonl"

def log(**e):
    e["t"] = time.time()
    with open(LOG, "a") as f:
        f.write(json.dumps(e) + "\n")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _send(self, code, body, ctype="text/plain", extra=None):
        self.send_response(code); self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        log(ev="http", method="GET", path=self.path, host=self.headers.get("Host"), peer=self.client_address[0])
        if self.path == "/redirect":
            return self._send(302, b"", extra={"Location": "http://denied-srv/"})
        if self.path == "/sse":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
            for i in range(5):
                self.wfile.write(f"data: event {i}\n\n".encode()); self.wfile.flush(); time.sleep(0.6)
            return
        self._send(200, f"hello from {NAME}\n".encode())
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0")); got = 0
        try:  # count bytes ACTUALLY received; a cut connection ends the read early
            while got < n:
                chunk = self.rfile.read(min(65536, n - got))
                if not chunk:
                    break
                got += len(chunk)
        except Exception as e:
            log(ev="read-error", err=type(e).__name__)
        log(ev="http", method="POST", path=self.path, bytes=n, received=got, complete=(got == n), peer=self.client_address[0])
        if got < n:
            return
        self._send(200, f"got {n}\n".encode())

class S(ThreadingHTTPServer):
    daemon_threads = True
    def get_request(self):
        conn, addr = super().get_request()
        log(ev="tcp-accept", port=self.server_address[1], peer=addr[0])
        return conn, addr

def tls_ctx():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1()); n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = dt.datetime.now(dt.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(1)
         .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName(NAME)]), False).sign(k, hashes.SHA256()))
    open("/tmp/s.crt", "wb").write(c.public_bytes(serialization.Encoding.PEM))
    open("/tmp/s.key", "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain("/tmp/s.crt", "/tmp/s.key"); return ctx

def udp(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("0.0.0.0", port))
    while True:
        data, addr = s.recvfrom(4096); log(ev="udp", port=port, peer=addr[0], bytes=len(data))

os.makedirs("/log", exist_ok=True)
http_srv = S(("0.0.0.0", 80), H)
https_srv = S(("0.0.0.0", 443), H); ctx = tls_ctx()
https_srv.socket = ctx.wrap_socket(https_srv.socket, server_side=True)
for t in (lambda: http_srv.serve_forever(), lambda: https_srv.serve_forever(), lambda: udp(443), lambda: udp(9999)):
    threading.Thread(target=t, daemon=True).start()
log(ev="started")
while True:
    time.sleep(3600)
