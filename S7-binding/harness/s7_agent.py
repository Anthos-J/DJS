"""Runs INSIDE an agent container (hardened, shares the sidecar's netns, holds no credentials).
Usage: python s7_agent.py <cmd> [args]. Prints one JSON object.
  call <tool> [json-headers]   MCP tool call through the sidecar (http://127.0.0.1:8081/mcp)
  stream <n> <delay>           slow_stream through the sidecar; records progress arrival times
  tls <no-cert|rogue-cert|plain-http>   direct attempt on terminator:8443 bypassing the sidecar
  reach <host> <port>          raw TCP connect attempt
  scan                         search env, filesystem and /proc for credential material; patterns are read as a
                               JSON list from STDIN so they never appear in this process's own cmdline/environ"""
import asyncio, json, os, socket, ssl, sys, time

def out(d):
    print(json.dumps(d)); sys.exit(0)

cmd = sys.argv[1]

async def mcp_call(tool, headers, args=None, progress=None):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    async with Client(StreamableHttpTransport("http://127.0.0.1:8081/mcp", headers=headers)) as c:
        r = await c.call_tool(tool, args or {}, raise_on_error=False, progress_handler=progress)
        return {"ok": not r.is_error, "texts": [getattr(x, "text", None) for x in r.content or []]}

if cmd == "call":
    hdrs = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    try:
        out({"cmd": cmd, **asyncio.run(mcp_call(sys.argv[2], hdrs))})
    except Exception as e:
        out({"cmd": cmd, "ok": False, "exception": f"{type(e).__name__}: {e}"[:400]})

if cmd == "stream":
    n, delay = int(sys.argv[2]), float(sys.argv[3]); t0 = time.monotonic(); events = []
    async def prog(p, total, msg):
        events.append(round(time.monotonic() - t0, 3))
    try:
        r = asyncio.run(mcp_call("slow_stream", {}, {"n": n, "delay": delay}, prog))
        out({"cmd": cmd, **r, "progress_arrivals_s": events, "total_s": round(time.monotonic() - t0, 3)})
    except Exception as e:
        out({"cmd": cmd, "ok": False, "exception": f"{type(e).__name__}: {e}"[:400], "progress_arrivals_s": events})

if cmd == "tls":
    mode = sys.argv[2]; host, port = "terminator", 8443
    req = b"POST /mcp HTTP/1.1\r\nHost: terminator\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
    try:
        raw = socket.create_connection((host, port), 5)
    except Exception as e:
        out({"cmd": cmd, "mode": mode, "stage": "tcp", "reached_pep": False, "error": f"{type(e).__name__}: {e}"})
    if mode == "plain-http":
        raw.sendall(req); data = raw.recv(4096)
        out({"cmd": cmd, "mode": mode, "stage": "http", "response_head": data[:200].decode(errors="replace")})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE  # attacker does not care about server auth
    if mode == "rogue-cert":
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime as dt
        k = ec.generate_private_key(ec.SECP256R1()); n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cell-a")])
        now = dt.datetime.now(dt.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(1)
             .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(hours=1)).sign(k, hashes.SHA256()))
        open("/tmp/rogue.crt", "wb").write(c.public_bytes(serialization.Encoding.PEM))
        open("/tmp/rogue.key", "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        ctx.load_cert_chain("/tmp/rogue.crt", "/tmp/rogue.key")
        os.remove("/tmp/rogue.key"); os.remove("/tmp/rogue.crt")  # throwaway attacker material; keeps later scans clean
    try:
        s = ctx.wrap_socket(raw, server_hostname=host)
        s.sendall(req); data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        out({"cmd": cmd, "mode": mode, "stage": "tls-ok", "response_head": data[:300].decode(errors="replace")})
    except Exception as e:
        out({"cmd": cmd, "mode": mode, "stage": "tls-or-http", "error": f"{type(e).__name__}: {e}"[:300]})

if cmd == "reach":
    host, port = sys.argv[2], int(sys.argv[3])
    try:
        socket.create_connection((host, port), 4).close(); out({"cmd": cmd, "target": f"{host}:{port}", "reached": True})
    except Exception as e:
        out({"cmd": cmd, "target": f"{host}:{port}", "reached": False, "error": f"{type(e).__name__}: {e}"[:200]})

if cmd == "scan":
    plist = json.loads(sys.stdin.read()); pats = [p.encode() for p in plist]; hits = []
    for k, v in os.environ.items():
        if any(p in (k + "=" + v).encode() for p in pats):
            hits.append({"where": "env", "key": k})
    skip = ("/proc", "/sys", "/dev", "/usr/lib", "/usr/local/lib", "/usr/share")
    for root, dirs, files in os.walk("/", topdown=True):
        dirs[:] = [d for d in dirs if not os.path.join(root, d).startswith(skip)]
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.islink(p) or os.path.getsize(p) > 5_000_000:
                    continue
                data = open(p, "rb").read()
            except Exception:
                continue
            if any(x in data for x in pats):
                hits.append({"where": "file", "path": p})
    for pid in [d for d in os.listdir("/proc") if d.isdigit()]:
        for part in ("environ", "cmdline"):
            try:
                data = open(f"/proc/{pid}/{part}", "rb").read()
            except Exception:
                continue
            if any(x in data for x in pats):
                hits.append({"where": f"/proc/{pid}/{part}"})
    procs = []
    for pid in [d for d in os.listdir("/proc") if d.isdigit()]:
        try:
            procs.append(open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()[:80])
        except Exception:
            pass
    out({"cmd": cmd, "n_patterns": len(plist), "hits": hits, "visible_processes": procs, "secrets_dir_exists": os.path.exists("/secrets")})

out({"error": f"unknown cmd {cmd}"})
