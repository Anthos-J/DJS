"""MANDATE control plane: the drift engine + REST API + dashboard (Starlette/uvicorn, as pinned in the spike image).
Callers:
  * the PEP (header X-PEP-Token) -> POST /api/decide for every tool call (fail closed at the PEP if unreachable)
  * the owner / operator UI (header X-Owner-Token)  -> registry, status, approvals, delegation, task/role changes
  * read-only views (agents, timeline, alerts, baselines, delegations, evaluation, audit) need the owner token too.
Tokens are DEMO values from the environment (MANDATE_PEP_TOKEN / MANDATE_OWNER_TOKEN); not production auth."""
import glob, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from mandate.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
PEP_TOKEN = os.environ.get("MANDATE_PEP_TOKEN", "demo-pep-token")
OWNER_TOKEN = os.environ.get("MANDATE_OWNER_TOKEN", "demo-owner-token")
AUDIT = os.environ.get("MANDATE_AUDIT", "/data/audit.jsonl")
os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
ENGINE = Engine(policy_dir=os.environ.get("MANDATE_POLICY_DIR"), audit_path=AUDIT)
SIMULATED = {"baseline_source": None}


def J(x, status=200):
    return JSONResponse(x, status_code=status)


def owner(req):
    return req.headers.get("x-owner-token") == OWNER_TOKEN


def need_owner(fn):
    async def w(req):
        if not owner(req):
            return J({"error": "owner token required"}, 401)
        return await fn(req)
    return w


async def decide(req):
    if req.headers.get("x-pep-token") != PEP_TOKEN:
        return J({"error": "PEP token required"}, 401)
    try:
        ev = await req.json()
    except Exception:
        return J({"response": "DENY", "reason": "malformed request (fail closed)"}, 400)
    ev["observed_by"] = "pep"
    return J(ENGINE.decide(ev))


@need_owner
async def agents(req):
    if req.method == "POST":
        b = await req.json()
        return J(ENGINE.register_agent(b["agent_id"], b["role"], owner=b.get("owner", "owner"), task=b.get("task"), instruction=b.get("instruction", "")))
    out = []
    for a in ENGINE.agents.values():
        bv = ENGINE.baseline_view(a["agent_id"])
        out.append({**a, "mandate": ENGINE.roles[a["role"]], "cold_start": bv["cold_start"], "drift_js": bv["drift_js"], "accumulator": bv["accumulator"],
                    "open_alerts": sum(1 for x in ENGINE.alerts if x["agent_id"] == a["agent_id"] and x["status"] == "open")})
    return J(out)


@need_owner
async def agent_status(req):
    b = await req.json(); aid = req.path_params["aid"]
    if not b.get("reason"):
        return J({"error": "a reason is required"}, 400)
    ENGINE.set_status(aid, b["status"], b["reason"], by="owner-ui")
    return J(ENGINE.agents[aid])


@need_owner
async def agent_task(req):
    b = await req.json(); aid = req.path_params["aid"]
    try:
        if b.get("role"):
            ENGINE.change_role(aid, b["role"], by="owner-ui")
        if b.get("task"):
            ENGINE.assign_task(aid, b["task"], b.get("instruction", ""), by="owner-ui")
    except ValueError as e:
        return J({"error": str(e)}, 400)
    return J(ENGINE.agents[aid])


@need_owner
async def baseline(req):
    return J(ENGINE.baseline_view(req.path_params["aid"]))


@need_owner
async def events(req):
    aid = req.query_params.get("agent")
    ev = [e for e in ENGINE.events if not aid or e["agent_id"] == aid]
    return J(ev[-int(req.query_params.get("limit", 300)):])


@need_owner
async def alerts(req):
    return J(list(reversed(ENGINE.alerts[-300:])))


@need_owner
async def approvals(req):
    if req.method == "POST":
        b = await req.json()
        try:
            return J(ENGINE.resolve_approval(req.path_params["apid"], bool(b.get("approve")), by="owner-ui", note=b.get("note", "")))
        except (KeyError, ValueError) as e:
            return J({"error": str(e)}, 400)
    return J(list(reversed(list(ENGINE.approvals.values()))))


@need_owner
async def delegations(req):
    if req.method == "POST":
        b = await req.json()
        try:
            return J(ENGINE.delegate(b["parent"], b["child"], b["scopes"], b.get("task")))
        except (PermissionError, KeyError) as e:
            return J({"error": str(e)}, 403)
    return J(list(ENGINE.delegations.values()))


@need_owner
async def audit(req):
    v = ENGINE.audit.verify()
    return J({"verify": v, "records": ENGINE.audit.records[-int(req.query_params.get("limit", 200)):]})


@need_owner
async def evaluation(req):
    out = {}
    for name, pat in [("heldout", "eval/runs/*heldout-run*/summary.json"), ("redteam", "eval/runs/*redteam*/redteam_results.json"),
                      ("e2e", "e2e/runs/*/e2e_summary.json")]:
        files = sorted(glob.glob(str(ROOT / pat)))
        if files:
            d = json.loads(Path(files[-1]).read_text())
            out[name] = {"file": str(Path(files[-1]).relative_to(ROOT)), "data": d}
    return J(out)


@need_owner
async def seed(req):
    """Load the declared demo agents and a SIMULATED benign history (labelled as such in the UI)."""
    b = await req.json() if (await req.body()) else {}
    for a in b.get("agents", []):
        if a["agent_id"] not in ENGINE.agents:
            ENGINE.register_agent(a["agent_id"], a["role"], task=a.get("task"), instruction=a.get("instruction", ""))
    if b.get("history"):
        ENGINE.learn(b["history"]); SIMULATED["baseline_source"] = b.get("source", "simulated benign history")
    return J({"agents": list(ENGINE.agents), "baseline_source": SIMULATED["baseline_source"]})


async def meta(req):
    return J({"service": "mandate-control", "engine_config": ENGINE.cfg["version"], "cedar": ENGINE.P is not None,
              "baseline_source": SIMULATED["baseline_source"], "time": time.time(),
              "notes": ["Risk score is an ordinal 0-100 index of documented factors, not a probability.",
                        "Demo tokens; no production authentication.", "Agents in the demo are scripted (no LLM)."]})


async def index(req):
    return FileResponse(ROOT / "control" / "static" / "index.html")


app = Starlette(routes=[
    Route("/", index), Route("/api/meta", meta), Route("/api/decide", decide, methods=["POST"]),
    Route("/api/agents", agents, methods=["GET", "POST"]), Route("/api/agents/{aid}/status", agent_status, methods=["POST"]),
    Route("/api/agents/{aid}/task", agent_task, methods=["POST"]), Route("/api/agents/{aid}/baseline", baseline),
    Route("/api/events", events), Route("/api/alerts", alerts), Route("/api/approvals", approvals),
    Route("/api/approvals/{apid}", approvals, methods=["POST"]), Route("/api/delegations", delegations, methods=["GET", "POST"]),
    Route("/api/audit", audit), Route("/api/eval", evaluation), Route("/api/seed", seed, methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(ROOT / "control" / "static")), name="static")])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8800")))
