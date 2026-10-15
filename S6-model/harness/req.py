"""Raw HTTP client for S6 (runs in the agent / outside containers). Reads a JSON spec from stdin:
{"url": ..., "body": "<raw text, sent byte-for-byte>", "headers": {...}, "gzip": false, "sse": false}
Prints {"status", "body", "arrivals"} or {"error"}. Raw bodies let tests send duplicate keys exactly as written."""
import gzip, http.client, json, sys, time
from urllib.parse import urlparse

spec = json.loads(sys.stdin.read())
u = urlparse(spec["url"])
raw = spec["body"].encode("utf-8")
hdrs = {"Content-Type": "application/json", **spec.get("headers", {})}
if spec.get("gzip"):
    raw = gzip.compress(raw); hdrs["Content-Encoding"] = "gzip"
hdrs["Content-Length"] = str(len(raw))
t0 = time.monotonic()
try:
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15)
    c.request("POST", u.path, body=raw, headers=hdrs)
    r = c.getresponse()
    arrivals, chunks = [], []
    if spec.get("sse"):
        while True:
            line = r.fp.readline()
            if not line:
                break
            if line.startswith(b"data:"):
                arrivals.append(round(time.monotonic() - t0, 3))
            chunks.append(line)
        body = b"".join(chunks)
    else:
        body = r.read()
    print(json.dumps({"status": r.status, "body": body.decode("utf-8", "replace")[:600], "arrivals": arrivals}))
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}))
