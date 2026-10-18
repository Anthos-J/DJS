"""MANDATE control plane: the drift engine + REST API + dashboard (Starlette/uvicorn, as pinned in the spike image).
Callers:
  * the PEP (header X-PEP-Token) -> POST /api/decide for every tool call (fail closed at the PEP if unreachable)
  * the owner / operator UI (header X-Owner-Token)  -> registry, status, approvals, delegation, task/role changes
  * read-only views (agents, timeline, alerts, baselines, delegations, evaluation, audit) need the owner token too.
Tokens are DEMO values from the environment (MANDATE_PEP_TOKEN / MANDATE_OWNER_TOKEN); not production auth."""
import copy, glob, json, os, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
ENGINE_VERSION = os.environ.get("MANDATE_ENGINE", "E2")   # E3 is opt-in; default stays the validated E2 engine
if ENGINE_VERSION == "E4.3.1":
    from mandate.engine_e431 import Engine
elif ENGINE_VERSION == "E4.3":
    from mandate.engine_e43 import Engine
elif ENGINE_VERSION == "E4.2.1":
    from mandate.engine_e421 import Engine
elif ENGINE_VERSION == "E4.2":
    from mandate.engine_e42 import Engine
elif ENGINE_VERSION == "E4.1":
    from mandate.engine_e41 import Engine
elif ENGINE_VERSION == "E4":
    from mandate.engine_e4 import Engine
elif ENGINE_VERSION == "E3":
    from mandate.engine_e3 import Engine
elif ENGINE_VERSION == "E2":
    from mandate.engine import Engine
else:
    raise SystemExit(f"unknown MANDATE_ENGINE {ENGINE_VERSION!r}")

ROOT = Path(__file__).resolve().parent.parent
PEP_TOKEN = os.environ.get("MANDATE_PEP_TOKEN", "demo-pep-token")
OWNER_TOKEN = os.environ.get("MANDATE_OWNER_TOKEN", "demo-owner-token")
AUDIT = os.environ.get("MANDATE_AUDIT", "/data/audit.jsonl")
os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
if ENGINE_VERSION in ("E4.2", "E4.2.1", "E4.3", "E4.3.1"):   # durable, single-writer security state; a refused start exits (the PEP then fails closed)
    from mandate.state_e42 import StateError
    try:
        ENGINE = Engine(policy_dir=os.environ.get("MANDATE_POLICY_DIR"), audit_path=AUDIT,
                        state_dir=os.environ.get("MANDATE_STATE_DIR", os.path.join(os.path.dirname(AUDIT), "state")),
                        state_key=os.environ.get("MANDATE_STATE_KEY"), anchor_path=os.environ.get("MANDATE_STATE_ANCHOR"),
                        recovery=os.environ.get("MANDATE_RECOVERY") == "1")
    except StateError as e:
        print(f"MANDATE control plane REFUSED TO START (fail closed): {e}", file=sys.stderr, flush=True)
        raise SystemExit(3)
else:
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


async def observe(req):
    """PEP-only: what an allowed read returned (post-execution content scan)."""
    if req.headers.get("x-pep-token") != PEP_TOKEN:
        return J({"error": "PEP token required"}, 401)
    if not hasattr(ENGINE, "observe_content"):
        return J({"scanned": False})
    ev = await req.json()
    if ENGINE_VERSION == "E4.3.1":   # E4.3.1 accepts the PEP's truncation flag (unverified -> taint)
        return J(ENGINE.observe_content(ev.get("agent_id"), ev.get("tool"), ev.get("decision_id"), ev.get("text", ""), truncated=bool(ev.get("truncated"))))
    return J(ENGINE.observe_content(ev.get("agent_id"), ev.get("tool"), ev.get("decision_id"), ev.get("text", "")))


@need_owner
async def agents(req):
    if req.method == "POST":
        b = await req.json()
        scope = {k: b[k] for k in ("subjects", "requester") if b.get(k) is not None}   # UI-P1: structured HR scope on registration
        try:
            return J(ENGINE.register_agent(b["agent_id"], b["role"], owner=b.get("owner", "owner"), task=b.get("task"), instruction=b.get("instruction", ""), **scope))
        except (ValueError, KeyError) as e:
            return J({"error": str(e)}, 400)
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
            scope = {k: b[k] for k in ("subjects", "requester") if b.get(k) is not None}   # owner-declared structured scope (E3+)
            ENGINE.assign_task(aid, b["task"], b.get("instruction", ""), by="owner-ui", **scope)
    except ValueError as e:
        return J({"error": str(e)}, 400)
    return J(ENGINE.agents[aid])


@need_owner
async def recovery_ack(req):
    b = await req.json() if (await req.body()) else {}
    if not hasattr(ENGINE, "ack_recovery"):
        return J({"error": "engine has no recovery mode"}, 400)
    ENGINE.ack_recovery(by="owner-ui", note=str(b.get("note", "")))
    return J({"recovery": ENGINE.recovery})


SKIP_COPY = {"lock", "audit", "store", "P", "S", "clock", "events", "alerts",
             "injection_scanner", "lm"}   # R-E4.3: read-only model objects are shared, not copied (an ONNX session cannot be deep-copied)


def sandbox():
    """UI-P2 what-if: a throwaway copy of the live engine state. It has no store (nothing persisted), an in-memory
    audit (the real chain is untouched), and no PEP or tool server behind it, so nothing can execute."""
    from mandate.audit import AuditLog
    with ENGINE.lock:
        sim = copy.copy(ENGINE)
        for k, v in vars(ENGINE).items():
            if k not in SKIP_COPY:
                setattr(sim, k, copy.deepcopy(v))
    sim.lock, sim.audit, sim.events, sim.alerts = threading.RLock(), AuditLog(None), [], []
    if hasattr(sim, "store"):
        sim.store = None
    return sim


@need_owner
async def simulate(req):
    b = await req.json()
    if not isinstance(b, dict) or not b.get("agent_id") or not b.get("tool"):
        return J({"error": "agent_id and tool are required"}, 400)
    before = (len(ENGINE.events), len(ENGINE.audit.records), len(ENGINE.approvals))
    rec = sandbox().decide({"agent_id": b["agent_id"], "tool": b["tool"], "args": b.get("args") or {}, "destination": b.get("destination") or "internal"})
    after = (len(ENGINE.events), len(ENGINE.audit.records), len(ENGINE.approvals))
    return J({"simulation": True, "executed": False, "live_state_unchanged": before == after,
              "note": "Dry run on a copy of the live state: not sent to the PEP or the tool server, not written to the audit, no approval created.",
              "decision": {k: rec.get(k) for k in ("response", "reason", "control", "risk_score", "risk_band", "confidence", "factors", "expected_authority",
                                                   "agent_status_change", "cedar", "provenance_label")}})


@need_owner
async def simulate_plan(req):
    """R-E4.3.1 workbench: a whole plan, in order, on ONE throwaway copy of the live state (so a read's taint carries to later
    steps). Nothing is sent to the PEP or the tool server; the real audit, approvals and agents are untouched. Content checks
    (the injection detector) need real tool output, so they run only on the real path."""
    b = await req.json()
    steps = b.get("steps") if isinstance(b, dict) else None
    if not b.get("agent_id") or not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        return J({"error": "agent_id and 1-20 steps are required"}, 400)
    before = (len(ENGINE.events), len(ENGINE.audit.records), len(ENGINE.approvals))
    sim, out = sandbox(), []
    for s in steps:
        if not isinstance(s, dict) or not isinstance(s.get("tool"), str):
            return J({"error": "each step needs a tool name"}, 400)
        rec = sim.decide({"agent_id": b["agent_id"], "tool": s["tool"], "args": s.get("args") if isinstance(s.get("args"), dict) else {},
                          "destination": s.get("destination") or "internal"})
        out.append({"tool": s["tool"], "args": s.get("args") or {}, **{k: rec.get(k) for k in ("response", "reason", "control", "risk_score", "risk_band",
                                                                                              "confidence", "factors", "expected_authority", "cedar")}})
    after = (len(ENGINE.events), len(ENGINE.audit.records), len(ENGINE.approvals))
    return J({"simulation": True, "executed": False, "live_state_unchanged": before == after, "steps": out,
              "note": "Dry run of the whole plan on one copy of the live state. Document content is not available in a dry run, so the injection detector does not run here."})


@need_owner
async def content_preview(req):
    """R-E4.3.1 workbench: score a document with the loaded detector. Read-only: no session, audit or alert is changed.
    It is a preview only; the real protection is the post-read scan on the PEP path."""
    b = await req.json()
    s = getattr(ENGINE, "injection_scanner", None)
    text = b.get("text") if isinstance(b, dict) else None
    if not isinstance(text, str) or len(text) > 200_000:
        return J({"error": "text (a string up to 200,000 characters) is required"}, 400)
    if s is None:
        return J({"available": False, "note": "this engine has no loaded injection detector"})
    r = s.scan_document(text)
    return J({"available": True, "preview_only": True, **{k: v for k, v in (r or {}).items() if k != "label"}})


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
    for name, pat in [("heldout2_e2", "eval/runs/*E2-heldout2-run*/summary.json"), ("heldout2_e1", "eval/runs/*E1-on-heldout2/summary.json"),
                      ("redteam_e2", "eval/runs/*redteam-E2/redteam_e2_results.json"),
                      ("heldout", "eval/runs/*heldout-run*/summary.json"), ("redteam", "eval/runs/*redteam-E1/redteam_results.json"),
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
    st = getattr(ENGINE, "store", None)    # UI-P1: runtime mode, recovery and persistence status for the console
    v = ENGINE.audit.verify()
    return J({"service": "mandate-control", "engine": ENGINE_VERSION, "engine_config": ENGINE.cfg["version"], "cedar": ENGINE.P is not None,
              "recovery": bool(getattr(ENGINE, "recovery", False)), "recovery_reason": getattr(ENGINE, "recovery_reason", None),
              "persistence": {"state_dir": bool(st), "anchor": bool(st and st.anchor), "signed": bool(st and st.key),
                              "findings": list(st.findings) if st else []},
              "audit": {"ok": v["ok"], "records": len(ENGINE.audit.records)},
              "counts": {"agents": len(ENGINE.agents), "pending_approvals": sum(1 for a in ENGINE.approvals.values() if a["status"] == "pending"),
                         "quarantined": sum(1 for a in ENGINE.agents.values() if a["status"] == "quarantined"),
                         "alerts": len(ENGINE.alerts), "decisions": len(ENGINE.events)},
              "injection_detector": _detector_status(), "learned_sequence_model": _sequence_status(),
              "baseline_source": SIMULATED["baseline_source"], "time": time.time(),
              "notes": ["Risk score is an ordinal 0-100 index of documented factors, not a probability.",
                        "Demo tokens; no production authentication.",
                        "Demo agents are scripted; an optional live-LLM agent (Groq) runs only when the owner enables it."]})


def _detector_status():
    """Release R-E4.3: what the engine actually loaded (read-only; no decision logic here)."""
    s = getattr(ENGINE, "injection_scanner", None)
    if not hasattr(ENGINE, "injection_scanner"):
        return {"present_in_engine": False}
    prov = (getattr(s, "provenance", None) or {}) if s else {}
    return {"present_in_engine": True, "enabled": s is not None, "threshold": getattr(s, "threshold", None),
            "scan_tools": list(ENGINE.cfg.get("injection_scan_tools", [])),
            "not_scanned": "structured records (prices, HR record, metrics, supplier catalogue) are outside the detector's scope",
            "model": prov.get("model"), "trained_by": "owner (Colab)", "when": "after an allowed document read, before the agent sees it"}


def _sequence_status():
    lm = getattr(ENGINE, "lm", None)
    if not hasattr(ENGINE, "lm"):
        return {"present_in_engine": False}
    return {"present_in_engine": True, "loaded": lm is not None, "points": ENGINE.cfg["points"].get("learned_sequence_anomaly"),
            "mode": "alert-only (0 points: recorded, never changes a decision)"}


async def index(req):
    return FileResponse(ROOT / "control" / "static" / "index.html")


app = Starlette(routes=[
    Route("/", index), Route("/api/meta", meta), Route("/api/decide", decide, methods=["POST"]), Route("/api/observe", observe, methods=["POST"]),
    Route("/api/agents", agents, methods=["GET", "POST"]), Route("/api/agents/{aid}/status", agent_status, methods=["POST"]),
    Route("/api/agents/{aid}/task", agent_task, methods=["POST"]), Route("/api/agents/{aid}/baseline", baseline),
    Route("/api/events", events), Route("/api/alerts", alerts), Route("/api/approvals", approvals),
    Route("/api/approvals/{apid}", approvals, methods=["POST"]), Route("/api/delegations", delegations, methods=["GET", "POST"]),
    Route("/api/audit", audit), Route("/api/simulate", simulate, methods=["POST"]), Route("/api/simulate_plan", simulate_plan, methods=["POST"]), Route("/api/content/preview", content_preview, methods=["POST"]), Route("/api/recovery/ack", recovery_ack, methods=["POST"]), Route("/api/eval", evaluation), Route("/api/seed", seed, methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(ROOT / "control" / "static")), name="static")])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8800")))
