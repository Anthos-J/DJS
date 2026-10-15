"""S6 model-route proxy addon (mitmproxy 12.2.3, reverse mode). Spike harness only.
Fail-closed ALLOWLIST, applied before any upstream contact:
  - only POST /v1/messages (Anthropic-shaped) and POST /v1/responses (OpenAI Responses-shaped);
  - body must be identity-encoded UTF-8 JSON whose top level is an object; DUPLICATE KEYS at any depth -> reject;
  - top-level keys must be in a per-API allowlist (so `mcp_servers`, `container`, unknown fields -> reject);
  - Anthropic tools: no `type` or exactly "custom"; keys {name, description, input_schema, type} only;
  - OpenAI tools: exactly type "function"; keys {type, name, description, parameters, strict} only;
  - the request is RE-SERIALIZED from the parsed object, so the provider receives exactly what was checked;
  - client-supplied credentials are dropped; the proxy injects the provider key (the cell holds none)."""
import json, os, time
from mitmproxy import http

LOG = os.environ.get("MODEL_LOG", "/log/model_proxy.jsonl")
PROVIDER_KEY = os.environ["PROVIDER_KEY"]          # dummy key; lives only in this container
ANTHROPIC_TOP = {"model", "messages", "max_tokens", "system", "tools", "tool_choice", "temperature", "top_p", "top_k",
                 "stop_sequences", "stream", "metadata"}
OPENAI_TOP = {"model", "input", "instructions", "tools", "tool_choice", "temperature", "top_p", "max_output_tokens",
              "stream", "metadata"}
ANTHROPIC_TOOL_KEYS = {"name", "description", "input_schema", "type"}
OPENAI_TOOL_KEYS = {"type", "name", "description", "parameters", "strict"}
DROP_HEADERS = {"x-api-key", "authorization", "proxy-authorization", "cookie", "content-encoding", "openai-organization",
                "openai-project", "anthropic-beta"}

class Reject(Exception):
    pass

def log(**e):
    e["t"] = time.time()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(e) + "\n")

def no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Reject(f"duplicate JSON key(s): {sorted({k for k in keys if keys.count(k) > 1})}")
    return dict(pairs)

def check_anthropic(b):
    extra = set(b) - ANTHROPIC_TOP
    if extra:
        raise Reject(f"top-level field(s) not allowed: {sorted(extra)}")
    tools = b.get("tools", [])
    if not isinstance(tools, list):
        raise Reject("tools must be a list")
    for t in tools:
        if not isinstance(t, dict):
            raise Reject("tool must be an object")
        if "type" in t and t["type"] != "custom":
            raise Reject(f"tool type not allowed: {t['type']!r}")
        if set(t) - ANTHROPIC_TOOL_KEYS:
            raise Reject(f"tool field(s) not allowed: {sorted(set(t) - ANTHROPIC_TOOL_KEYS)}")
        if not isinstance(t.get("name"), str):
            raise Reject("tool name missing")

def check_openai(b):
    extra = set(b) - OPENAI_TOP
    if extra:
        raise Reject(f"top-level field(s) not allowed: {sorted(extra)}")
    tools = b.get("tools", [])
    if not isinstance(tools, list):
        raise Reject("tools must be a list")
    for t in tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            raise Reject(f"tool type not allowed: {t.get('type') if isinstance(t, dict) else t!r}")
        if set(t) - OPENAI_TOOL_KEYS:
            raise Reject(f"tool field(s) not allowed: {sorted(set(t) - OPENAI_TOOL_KEYS)}")

def request(flow: http.HTTPFlow):
    req = flow.request
    try:
        if req.method != "POST" or req.path.split("?")[0] not in ("/v1/messages", "/v1/responses"):
            raise Reject(f"route not allowed: {req.method} {req.path}")
        enc = req.headers.get("content-encoding", "identity").lower()
        if enc not in ("", "identity"):
            raise Reject(f"content-encoding not allowed: {enc}")
        try:
            body = json.loads(req.raw_content.decode("utf-8"), object_pairs_hook=no_dupes)
        except Reject:
            raise
        except Exception as e:
            raise Reject(f"body is not UTF-8 JSON: {type(e).__name__}")
        if not isinstance(body, dict):
            raise Reject("top-level JSON must be an object")
        api = "anthropic" if req.path.startswith("/v1/messages") else "openai"
        (check_anthropic if api == "anthropic" else check_openai)(body)
    except Reject as r:
        flow.response = http.Response.make(400, json.dumps({"error": "model-proxy rejected", "why": str(r)}).encode(),
                                           {"Content-Type": "application/json"})
        log(ev="reject", why=str(r), path=req.path, client_had_key=("x-api-key" in req.headers or "authorization" in req.headers))
        return
    client_creds = [h for h in ("x-api-key", "authorization") if h in req.headers]
    for h in list(req.headers.keys()):
        if h.lower() in DROP_HEADERS:
            del req.headers[h]
    canonical = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode()
    req.raw_content = canonical          # forward exactly what was checked
    # FIX (16 Oct, found by S8): raw_content does not update framing. A stale Content-Length made the provider wait
    # (canonical shorter) or TRUNCATE the body (canonical longer) -> provider parsed something other than what was checked.
    req.headers.pop("transfer-encoding", None)
    req.headers["content-length"] = str(len(canonical))
    if api == "anthropic":
        req.headers["x-api-key"] = PROVIDER_KEY
    else:
        req.headers["authorization"] = f"Bearer {PROVIDER_KEY}"
    log(ev="forward", api=api, path=req.path, n_tools=len(body.get("tools", [])), client_creds_dropped=client_creds,
        sha256=__import__("hashlib").sha256(canonical).hexdigest())

def responseheaders(flow: http.HTTPFlow):
    if flow.response:
        flow.response.stream = True
