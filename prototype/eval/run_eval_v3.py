"""E3 evaluation harness (run_eval.py / run_eval_v2.py are kept unchanged).
Usage: python eval/run_eval_v3.py <out_dir> <split: h3dev|h3eval> <seeds> <engine: E2|E3>
Every scenario gets exactly ONE final outcome (see eval/audit_outcomes.py); alert timing BEFORE/AT/NONE recorded.
*** Engine-level evaluation on generated scenarios: not LLM behaviour, not real-world attack rates. ***
Adds per-attack attribution of the control that stopped the harmful action, separates deny from approval-gate
(which needs a human to reject), counts provenance-labelled mitigations separately from prevention, early
warnings (alert strictly before the first harmful action), quarantine events, and a per-scenario breakdown of
benign scenarios that did not complete cleanly."""
import hashlib, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import inspect
from eval import scenarios_heldout3

OUT, SPLIT = sys.argv[1], sys.argv[2]; SEEDS = [int(s) for s in sys.argv[3].split(",")]; ENGINE = sys.argv[4]
if ENGINE == "E3":
    from mandate.engine_e3 import Engine
else:
    from mandate.engine import Engine
REG_KW = set(inspect.signature(Engine.register_agent).parameters); TASK_KW = set(inspect.signature(Engine.assign_task).parameters)
os.makedirs(OUT, exist_ok=True)
ROOT = os.path.join(os.path.dirname(__file__), "..")
inputs = {f: hashlib.sha256(open(os.path.join(ROOT, f), "rb").read().replace(b"\r\n", b"\n")).hexdigest()
          for f in ["config/engine_config.json", "config/roles.json", "config/engine_config_e3.json", "config/roles_e3.json", "mandate/engine.py",
                    "mandate/engine_e3.py", "eval/scenarios.py", "eval/scenarios_heldout2.py", "eval/scenarios_heldout3.py", "eval/run_eval_v3.py"]}


class Clock:
    def __init__(self):
        self.t, self.fast = 1_800_000_000.0, False
    def __call__(self):
        self.t += 1.0 if self.fast else 7.0
        return self.t


def run(sc):
    clk = Clock(); e = Engine(clock=clk)
    for a in sc["agents"]:
        kw = {k: a[k] for k in ("subjects", "requester") if k in a and k in REG_KW}
        e.register_agent(a["agent_id"], a["role"], task=a["task"], instruction=a["instruction"], **kw)
    e.learn(sc["history"])
    dlg = None; rows = []
    for i, act in enumerate(sc["trace"]):
        for o in [o for o in sc["owner_actions"] if o["at"] == i]:
            if o["op"] == "assign_task":
                try:
                    e.assign_task(o["agent"], o["task"], o["instruction"], **{k: o[k] for k in ("subjects", "requester") if k in o and k in TASK_KW})
                except ValueError as x:   # task not defined in this engine's role catalogue (E2 lacks the E3 batch tasks)
                    rows.append({"i": -1, "tool": "assign_task", "harmful": False, "response": "OWNER_ACTION_FAILED", "control": "n/a", "risk": None,
                                 "alert": False, "drift_alert": False, "provenance": None, "status_change": None, "mitigation_ok": None, "factors": [], "reason": str(x)})
            elif o["op"] == "change_role":
                e.change_role(o["agent"], o["role"])
            elif o["op"] == "delegate":
                dlg = e.delegate(o["parent"], o["child"], o["scopes"])["id"]
        clk.fast = bool(act.get("burst"))
        if act.get("dt") is not None:
            clk.t += act["dt"] - (1.0 if clk.fast else 7.0)
        ev = {k: v for k, v in act.items() if k not in ("harmful", "delegation", "burst", "mitigation_ok", "dt")}
        if act.get("delegation"):
            ev["delegation_id"] = dlg
        r = e.decide(ev)
        rows.append({"i": i, "tool": act["tool"], "harmful": act["harmful"], "response": r["response"], "control": r.get("control"),
                     "risk": r.get("risk_score"), "alert": bool(r.get("alert_id")), "drift_alert": r.get("drift_alert"),
                     "provenance": r.get("provenance_label"), "status_change": r.get("agent_status_change"),
                     "mitigation_ok": act.get("mitigation_ok"), "factors": [f["factor"] for f in r.get("factors", [])], "reason": r.get("reason")})
    return rows, e.audit.verify()


res, t0 = [], time.time()
for seed in SEEDS:
    for sc in scenarios_heldout3.generate(SPLIT, seed):
        rows, audit = run(sc)
        rows = [r for r in rows if r["i"] >= 0] + [r for r in rows if r["i"] < 0]
        harm = [r for r in rows if r["harmful"]]; first = min((r["i"] for r in harm), default=None)
        exe = [r for r in harm if r["response"] == "ALLOW"]
        labelled = bool(exe) and all(r["mitigation_ok"] == "provenance" and r["provenance"] == "untrusted" for r in exe)
        res.append({"id": sc["id"], "family": sc["family"], "kind": sc["kind"], "challenge": sc["challenge"], "seed": seed,
                    "harmful_total": len(harm), "executed_harmful": len(exe), "mitigated_by_provenance_label": labelled,
                    "blocked": any(r["response"] == "DENY" for r in harm), "gated": any(r["response"] == "APPROVAL_REQUIRED" for r in harm),
                    "stopping_control": next((r["control"] for r in harm if r["response"] != "ALLOW"), None),
                    "early_warning": any(r["alert"] for r in rows if first is not None and r["i"] < first),
                    "quarantined": any(r["status_change"] == "quarantined" for r in rows),
                    "benign_total": sum(1 for r in rows if not r["harmful"]),
                    "benign_executed": sum(1 for r in rows if not r["harmful"] and r["response"] == "ALLOW"),
                    "benign_approvals": sum(1 for r in rows if not r["harmful"] and r["response"] == "APPROVAL_REQUIRED"),
                    "benign_denies": sum(1 for r in rows if not r["harmful"] and r["response"] == "DENY"),
                    "benign_alerts": sum(1 for r in rows if not r["harmful"] and r["alert"]),
                    "audit_ok": audit["ok"], "rows": rows})

att = [r for r in res if r["kind"] == "attack"]; ben = [r for r in res if r["kind"] == "benign"]
prevented = [r for r in att if r["executed_harmful"] == 0]
by_ctrl = {}
for r in prevented:
    k = f"{r['stopping_control']} / {'deny' if r['blocked'] else 'approval gate (needs human rejection)'}"
    by_ctrl[k] = by_ctrl.get(k, 0) + 1
fam = {}
for r in res:
    f = fam.setdefault(r["family"], {"kind": r["kind"], "n": 0, "prevented": 0, "deny": 0, "gate_only": 0, "labelled": 0, "succeeded": 0, "early_warning": 0,
                                     "quarantined": 0, "completed": 0, "approvals": 0, "denies": 0, "alerts": 0})
    f["n"] += 1; f["quarantined"] += r["quarantined"]
    if r["kind"] == "attack":
        ok = r["executed_harmful"] == 0
        f["prevented"] += ok; f["deny"] += ok and r["blocked"]; f["gate_only"] += ok and not r["blocked"]
        f["labelled"] += r["mitigated_by_provenance_label"]; f["succeeded"] += (not ok and not r["mitigated_by_provenance_label"]); f["early_warning"] += r["early_warning"]
    else:
        f["completed"] += r["benign_executed"] == r["benign_total"]; f["approvals"] += r["benign_approvals"]; f["denies"] += r["benign_denies"]; f["alerts"] += r["benign_alerts"]
ben_actions = sum(r["benign_total"] for r in ben)
summary = {"LABEL": "engine-level evaluation on generated scenarios (not LLM behaviour, not real-world attack rates)",
           "engine": ENGINE, "split": SPLIT, "seeds": SEEDS, "inputs_sha256": inputs,
           "attack_scenarios": len(att), "prevented_total": len(prevented),
           "prevented_by_deny": sum(1 for r in prevented if r["blocked"]), "prevented_only_by_approval_gate": sum(1 for r in prevented if not r["blocked"]),
           "prevented_by_control": by_ctrl,
           "mitigated_by_provenance_label": len([r for r in att if r["mitigated_by_provenance_label"]]),
           "succeeded_unmitigated": [r["id"] for r in att if r["executed_harmful"] > 0 and not r["mitigated_by_provenance_label"]],
           "attacks_with_early_warning": sum(1 for r in att if r["early_warning"]),
           "quarantine_events": {"attack_scenarios": sum(1 for r in att if r["quarantined"]), "benign_scenarios": sum(1 for r in ben if r["quarantined"])},
           "benign_scenarios": len(ben), "benign_completed_cleanly": sum(1 for r in ben if r["benign_executed"] == r["benign_total"]),
           "benign_actions": ben_actions, "benign_actions_approval": sum(r["benign_approvals"] for r in ben),
           "benign_actions_denied": sum(r["benign_denies"] for r in ben), "benign_actions_alerted": sum(r["benign_alerts"] for r in ben),
           "benign_alert_rate_per_action": round(sum(r["benign_alerts"] for r in ben) / max(1, ben_actions), 4),
           "benign_not_clean": [{"id": r["id"], "approvals": r["benign_approvals"], "denies": r["benign_denies"],
                                 "causes": sorted({f"{x['control']}: {x['reason'][:60]}" for x in r["rows"] if not x["harmful"] and x["response"] != "ALLOW"})}
                                for r in ben if r["benign_executed"] != r["benign_total"]],
           "audit_chains_ok": all(r["audit_ok"] for r in res), "families": fam, "seconds": round(time.time() - t0, 1)}
summary["decision_hash"] = hashlib.sha256(json.dumps([[x["response"] for x in r["rows"]] for r in res]).encode()).hexdigest()
open(os.path.join(OUT, "results.jsonl"), "w").write("\n".join(json.dumps(r) for r in res) + "\n")
open(os.path.join(OUT, "summary.json"), "w").write(json.dumps(summary, indent=1))
print(json.dumps({k: v for k, v in summary.items() if k not in ("families", "benign_not_clean", "inputs_sha256")}, indent=1))
for name, v in fam.items():
    print("  ", name[:62].ljust(62), {k: x for k, x in v.items() if x and k != "kind"})
