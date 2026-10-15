"""S6 mock model provider (NOT a real API). Logs every TCP accept and every request (headers + raw body sha256 +
body) BEFORE responding, so 'provider received nothing' is judged here. Returns a fixed JSON reply, or an
SSE stream of 5 events 0.6 s apart when the body has "stream": true."""
import hashlib, json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/log/provider.jsonl"

def log(**e):
    e["t"] = time.time()
    with open(LOG, "a") as f:
        f.write(json.dumps(e) + "\n")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        log(ev="request", path=self.path, peer=self.client_address[0], headers={k.lower(): v for k, v in self.headers.items()},
            sha256=hashlib.sha256(raw).hexdigest(), body=raw.decode("utf-8", "replace")[:4000])
        try:
            stream = json.loads(raw).get("stream") is True
        except Exception:
            stream = False
        if stream:
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for i in range(5):
                self.wfile.write(f"event: delta\ndata: {{\"i\": {i}}}\n\n".encode()); self.wfile.flush(); time.sleep(0.6)
            return
        out = json.dumps({"mock": True, "path": self.path}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out)))
        self.end_headers(); self.wfile.write(out)

class S(ThreadingHTTPServer):
    daemon_threads = True
    def get_request(self):
        c, a = super().get_request(); log(ev="tcp-accept", peer=a[0]); return c, a

os.makedirs("/log", exist_ok=True)
log(ev="started")
S(("0.0.0.0", 9000), H).serve_forever()
