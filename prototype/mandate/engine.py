"""MANDATE behavioural-drift engine (prototype).

Decision = deterministic enforcement FIRST (it always wins), then a behavioural risk assessment that can only make the
response stricter. Responses: ALLOW, APPROVAL_REQUIRED, DENY, plus agent-level RESTRICT / QUARANTINE.

Deterministic layer (in order): credential validity -> quarantine -> role mandate (tool) -> sensitivity ceiling ->
delegation scope (chain-attenuated) -> destination allowlist -> frozen S2 Cedar policy P (two-pass, AM9) for
effectful actions -> restricted-agent step-up -> one-time owner approvals.
Behavioural layer: role/agent baselines (frequencies of tool / destination, action rate), novelty, rarity,
task-scope deviation, untrusted-content influence, sliding-window distribution drift (Jensen-Shannon), repeated
anomalies, impact, sensitivity. Score is an ordinal 0-100 sum of documented factor points (engine_config.json),
NOT a probability. Cold start (agent history < cold_start_min_events) uses the role prior and is labelled low-confidence.
"""
import copy, fnmatch, hashlib, json, math, threading, time, uuid
from collections import Counter, defaultdict, deque
from pathlib import Path

from .audit import AuditLog

try:
    from cedarpy import is_authorized, Decision, PolicySet, Schema
    HAVE_CEDAR = True
except Exception:  # the engine refuses effectful actions if Cedar is unavailable (fail closed)
    HAVE_CEDAR = False

ROOT = Path(__file__).resolve().parent.parent
# factors that indicate DEVIATION from learned / declared behaviour; only these feed the drift accumulator and the
# repeated-anomaly window (policy step-ups awaiting approval and in-mandate impact/sensitivity do not).
LEARNED_DEVIATION = {"novel_tool", "novel_destination", "rarity", "rate_spike", "distribution_drift"}   # deviation from learned behaviour
DEVIATION = {"task_scope_deviation", "novel_tool", "novel_destination", "rarity", "rate_spike", "distribution_drift"}  # drift_alert itself scores 0


def _js(p, q):
    keys = set(p) | set(q)
    m = {k: 0.5 * (p.get(k, 0) + q.get(k, 0)) for k in keys}
    def kl(a):
        return sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a.get(k, 0) > 0)
    return 0.5 * kl(p) + 0.5 * kl(q)


def _norm(c):
    s = sum(c.values())
    return {k: v / s for k, v in c.items()} if s else {}


def _vals(v):
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, (list, tuple)):
        return [x for e in v for x in _vals(e)]
    if isinstance(v, float) and v.is_integer():
        return [str(int(v))]
    return [str(v)]


class Engine:
    def __init__(self, roles_path=None, config_path=None, policy_dir=None, audit_path=None, clock=time.time):
        self.cat = json.loads(Path(roles_path or ROOT / "config" / "roles.json").read_text(encoding="utf-8"))
        self.cfg = json.loads(Path(config_path or ROOT / "config" / "engine_config.json").read_text(encoding="utf-8"))
        self.tools, self.roles = self.cat["tools"], self.cat["roles"]
        self.clock = clock
        self.lock = threading.RLock()
        self.agents = {}                     # agent_id -> {role, status, task, task_instruction, created, owner}
        self.delegations = {}                # delegation_id -> {parent, child, scopes, task, root, chain}
        self.approvals = {}                  # approval_id -> {...}
        self.alerts = []
        self.events = []                     # decided events (timeline)
        self.role_base = defaultdict(lambda: {"tool": Counter(), "dest": Counter(), "n": 0})
        self.agent_base = defaultdict(lambda: {"tool": Counter(), "dest": Counter(), "n": 0, "rates": []})
        self.ref_tool = {}                   # FROZEN reference distributions for drift (not moved by online updates)
        self.recent = defaultdict(lambda: deque(maxlen=self.cfg["drift_window"]))
        self.recent_anom = defaultdict(lambda: deque(maxlen=self.cfg["repeat_window"]))
        self.times = defaultdict(lambda: deque(maxlen=500))
        self.accum = defaultdict(float)
        self.session = defaultdict(lambda: {"conf": 0, "integ": 2, "trusted_text": ""})
        self.effects = defaultdict(lambda: deque(maxlen=500))         # E2: executed effects (ts, tool, args_hash) for budgets
        self.dev_window = defaultdict(lambda: deque(maxlen=self.cfg.get("drift_alert_window", 10)))  # E2: deviation points per action
        self.store_labels = {}                                         # E2: provenance labels of objects in trusted stores
        self.audit = AuditLog(audit_path)
        pdir = Path(policy_dir or ROOT.parent / "S2-cedar" / "config")
        self.P = PolicySet.from_str((pdir / "policies_P.cedar").read_text()) if HAVE_CEDAR else None
        self.S = Schema.from_str((pdir / "schema.cedarschema").read_text()) if HAVE_CEDAR else None

    # ------------------------------------------------------------------ registry / owner actions
    def register_agent(self, agent_id, role, owner="owner", task=None, instruction=""):
        with self.lock:
            if role not in self.roles:
                raise ValueError(f"unknown role {role}")
            self.agents[agent_id] = {"agent_id": agent_id, "role": role, "status": "active", "task": task, "task_instruction": instruction,
                                     "owner": owner, "created": self.clock(), "history_n": self.agent_base[agent_id]["n"]}
            self.audit.append({"kind": "agent_registered", "agent": agent_id, "role": role, "owner": owner, "task": task})
            return self.agents[agent_id]

    def assign_task(self, agent_id, task, instruction="", by="owner"):
        """Owner-authorized, legitimate task change: the active scope moves; it is not drift."""
        with self.lock:
            a = self.agents[agent_id]
            if task not in self.roles[a["role"]]["tasks"]:
                raise ValueError(f"task {task} not defined for role {a['role']}")
            old = a["task"]; a["task"], a["task_instruction"] = task, instruction
            self.session[agent_id] = {"conf": 0, "integ": 2, "trusted_text": ""}
            self.recent[agent_id].clear(); self.dev_window[agent_id].clear()   # a declared task change is not drift
            self.audit.append({"kind": "task_changed", "agent": agent_id, "from": old, "to": task, "by": by})

    def change_role(self, agent_id, role, by="owner"):
        with self.lock:
            a = self.agents[agent_id]; old = a["role"]; a["role"] = role; a["task"] = None
            self.agent_base[agent_id] = {"tool": Counter(), "dest": Counter(), "n": 0, "rates": []}   # history no longer representative
            self.ref_tool.pop(agent_id, None)
            self.recent[agent_id].clear(); self.accum[agent_id] = 0.0; self.dev_window[agent_id].clear()
            self.audit.append({"kind": "role_changed", "agent": agent_id, "from": old, "to": role, "by": by})

    def set_status(self, agent_id, status, reason, by="owner"):
        assert status in ("active", "restricted", "quarantined")
        with self.lock:
            a = self.agents[agent_id]; old = a["status"]; a["status"] = status
            if status == "active":
                self.accum[agent_id] = 0.0; self.recent_anom[agent_id].clear()
            self.audit.append({"kind": "status_changed", "agent": agent_id, "from": old, "to": status, "reason": reason, "by": by})
            # containment propagates down delegation chains: a quarantined parent's delegations are suspended
            if status == "quarantined":
                for d in self.delegations.values():
                    if agent_id in d["chain"] and d["status"] == "active":
                        d["status"] = "suspended"
                        self.audit.append({"kind": "delegation_suspended", "delegation": d["id"], "because": agent_id})

    def delegate(self, parent, child, scopes, task=None):
        """Chain-attenuated delegation (G6): child scopes must be within parent's AND child's role tools."""
        with self.lock:
            p, c = self.agents[parent], self.agents[child]
            if p["status"] != "active":
                raise PermissionError(f"parent {parent} is {p['status']}")
            if c["role"] not in self.roles[p["role"]]["may_delegate_to"]:
                raise PermissionError(f"role {p['role']} may not delegate to {c['role']}")
            # attenuation: a child may use its own role's read tools plus scopes the parent itself holds
            child_tools = set(self.roles[c["role"]]["tools"])
            bad = [s for s in scopes if s not in child_tools or (self.tools[s]["class"] != "read" and s not in self.roles[p["role"]]["tools"])]
            if bad:
                raise PermissionError(f"scopes exceed attenuated authority: {bad}")
            chain = [parent]
            for d in self.delegations.values():
                if d["child"] == parent and d["status"] == "active":
                    chain = d["chain"] + [parent]
            did = "dlg-" + uuid.uuid4().hex[:8]
            self.delegations[did] = {"id": did, "parent": parent, "child": child, "scopes": sorted(scopes), "task": task,
                                     "chain": chain, "root": self.agents[chain[0]]["owner"], "status": "active", "created": self.clock()}
            self.audit.append({"kind": "delegation_created", **self.delegations[did]})
            return self.delegations[did]

    def resolve_approval(self, approval_id, approve, by="owner", note=""):
        with self.lock:
            ap = self.approvals[approval_id]
            if ap["status"] != "pending":
                raise ValueError("approval already resolved")
            ap["status"] = "approved" if approve else "rejected"; ap["resolved_by"] = by; ap["note"] = note; ap["resolved"] = self.clock()
            self.audit.append({"kind": "approval_resolved", "approval": approval_id, "status": ap["status"], "by": by, "note": note})
            return ap

    # ------------------------------------------------------------------ baselines
    def learn(self, events):
        """Learn baselines from benign observations (role prior + per-agent history)."""
        with self.lock:
            for e in events:
                a = self.agents.get(e["agent_id"]); role = e.get("role") or (a and a["role"])
                for b in (self.role_base[role], self.agent_base[e["agent_id"]]):
                    b["tool"][e["tool"]] += 1; b["dest"][e.get("destination") or "internal"] += 1; b["n"] += 1
            for aid in {e["agent_id"] for e in events}:
                if aid in self.agents:
                    self.agents[aid]["history_n"] = self.agent_base[aid]["n"]
                self.ref_tool[aid] = Counter(self.agent_base[aid]["tool"])
            for role in {e.get("role") or (self.agents.get(e["agent_id"]) or {}).get("role") for e in events}:
                self.ref_tool["role:" + str(role)] = Counter(self.role_base[role]["tool"])

    def baseline_view(self, agent_id):
        a = self.agents[agent_id]; ab = self.agent_base[agent_id]; rb = self.role_base[a["role"]]
        rec = Counter(x["tool"] for x in self.recent[agent_id])
        base = self.ref_tool.get(agent_id) or (ab["tool"] if ab["n"] >= self.cfg["cold_start_min_events"] else rb["tool"])
        return {"agent": agent_id, "role": a["role"], "history_n": ab["n"], "cold_start": ab["n"] < self.cfg["cold_start_min_events"],
                "baseline_tools": _norm(base), "recent_tools": _norm(rec), "drift_js": round(_js(_norm(rec), _norm(base)), 3) if rec and base else 0.0,
                "accumulator": round(self.accum[agent_id], 1), "quarantine_threshold": self.cfg["quarantine_drift_accumulator"]}

    # ------------------------------------------------------------------ deterministic helpers
    def _dest_ok(self, role, dest):
        dest = dest or "internal"
        return any(fnmatch.fnmatch(dest, pat) for pat in self.roles[role]["destinations"])

    def _cedar(self, ctx):
        if not HAVE_CEDAR:
            return "DENY"
        def ev(approved):
            c = copy.deepcopy(ctx); c["approved"] = approved
            return is_authorized({"principal": 'Agent::"procurement"', "action": 'Action::"send"', "resource": 'Sink::"sink"', "context": c}, self.P, [], schema=self.S)
        r1 = ev(True)
        if r1.diagnostics.errors or r1.decision != Decision.Allow:
            return "DENY"
        r2 = ev(False)
        if r2.diagnostics.errors:
            return "DENY"
        return "PERMIT" if r2.decision == Decision.Allow else "APPROVAL_REQUIRED"

    # ------------------------------------------------------------------ decision
    def decide(self, ev):
        """ev: {agent_id, tool, args, destination?, credential_valid?, delegation_id?, approval_id?, ts?}. Returns a decision record."""
        with self.lock:
            try:
                if not isinstance(ev, dict) or not isinstance(ev.get("agent_id"), str) or not isinstance(ev.get("tool"), str)                         or not isinstance(ev.get("args", {}) or {}, dict):
                    raise ValueError("malformed event")
                return self._decide(ev)
            except Exception as e:   # fail closed: any engine error is a DENY with the error recorded
                bad = ev if isinstance(ev, dict) else {"agent_id": "?", "tool": "?"}
                rec = {"decision_id": "dec-err-" + uuid.uuid4().hex[:8], "ts": self.clock(), "agent_id": str(bad.get("agent_id")),
                       "tool": str(bad.get("tool")), "response": "DENY", "reason": f"engine error (fail closed): {type(e).__name__}: {e}",
                       "risk_score": 100, "risk_band": "HIGH", "factors": [], "confidence": "n/a"}
                self.events.append(rec); self.audit.append({"kind": "decision_error", **rec})
                return rec

    def _decide(self, ev):
        cfg, pts = self.cfg, self.cfg["points"]
        now = ev.get("ts") or self.clock()
        aid, tool, args = ev["agent_id"], ev["tool"], dict(ev.get("args") or {})
        dest = ev.get("destination") or "internal"
        a = self.agents.get(aid)
        factors, hard, reasons = [], None, []

        def F(code, points, why):
            factors.append({"factor": code, "points": points, "evidence": why})

        if a is None:
            return self._finish(ev, now, None, "DENY", [], "unknown agent identity", factors, quarantine=False)
        role = a["role"]; rdef = self.roles[role]; tdef = self.tools.get(tool)
        expected = {"role": role, "mandate_tools": rdef["tools"], "max_sensitivity": rdef["max_sensitivity"],
                    "destinations": rdef["destinations"], "task": a["task"], "task_tools": rdef["tasks"].get(a["task"], rdef["tools"])}
        consequential = bool(tdef) and tdef["class"] in ("write", "send", "fetch", "delegate")

        # ---- deterministic enforcement (always wins) ----
        if ev.get("credential_valid") is False:
            hard = ("DENY", "credential invalid or not bound")
        elif a["status"] == "quarantined":
            hard = ("DENY", "agent is quarantined")
        elif tdef is None or tool not in rdef["tools"]:
            F("out_of_role", pts["out_of_role"], f"tool '{tool}' is not in the {role} mandate {rdef['tools']}")
            hard = ("DENY", "out-of-role action")
        elif tdef["sensitivity"] > rdef["max_sensitivity"]:
            F("sensitivity_ceiling", pts["sensitivity_ceiling"], f"resource '{tdef['resource']}' sensitivity {tdef['sensitivity']} > role ceiling {rdef['max_sensitivity']}")
            hard = ("DENY", "sensitivity ceiling")
        dlg = None
        if hard is None and ev.get("delegation_id"):
            dlg = self.delegations.get(ev["delegation_id"])
            if dlg is None or dlg["child"] != aid:
                F("authority_escalation", pts["authority_escalation"], "delegation id unknown or not issued to this agent")
                hard = ("DENY", "invalid delegation")
            elif dlg["status"] != "active":
                hard = ("DENY", f"delegation {dlg['id']} is {dlg['status']}")
            elif tool not in dlg["scopes"]:
                F("authority_escalation", pts["authority_escalation"], f"'{tool}' outside delegated scopes {dlg['scopes']} (chain {dlg['chain']})")
                hard = ("DENY", "authority escalation beyond delegated scope")
        if hard is None and tdef["class"] in ("send", "fetch") and not self._dest_ok(role, dest):
            F("unapproved_destination", pts["unapproved_destination"], f"destination '{dest}' not in role allowlist {rdef['destinations']}")
            hard = ("DENY", "destination not in mandate")

        sess = self.session[aid]
        cedar = None; stepups = []; provenance = False
        if hard is None and consequential:
            cons = [x for k in tdef.get("consequential", []) for x in _vals(args.get(k))]
            text = (a.get("task_instruction") or "").lower() + " " + sess["trusted_text"]
            grounded = all(c.lower() in text for c in cons)
            if tdef.get("ground_by_allowlist") and self._dest_ok(role, dest):
                grounded = True   # fetch targets are governed by the role's approved-source allowlist
            external = dest != "internal"
            ctx = {"session": {"conf": max(sess["conf"], tdef["sensitivity"]), "integ": sess["integ"]},
                   "target": {"external": external, "clearance": 0 if external else 3, "untrusted_threshold": 1},
                   "params": {"all_grounded": grounded}}
            cedar = self._cedar(ctx)
            if sess["integ"] == 0:
                F("untrusted_influence", pts["untrusted_influence"], "session has read untrusted content before this consequential action")
            if not grounded:
                F("ungrounded_consequential", pts["ungrounded_consequential"], f"consequential values {cons} not found in the task instruction or trusted outputs")
            if cedar == "DENY":
                hard = ("DENY", "policy P denied")
            elif cedar == "APPROVAL_REQUIRED":
                F("policy_step_up", pts["policy_step_up"], "policy P (G2/G3) requires approval")
            # E2 effect budget: availability / duplication attacks repeat an allowed effect
            win = tdef.get("budget_window_s")
            if win and hard is None:
                h = hashlib.sha256(json.dumps([tool, args], sort_keys=True).encode()).hexdigest()
                same = [e for e in self.effects[aid] if e[1] == tool and now - e[0] <= win]
                ident = [e for e in same if e[2] == h]
                if tdef.get("max_per_window") is not None and len(same) >= tdef["max_per_window"]:
                    F("effect_budget", pts["effect_budget"], f"'{tool}' already executed {len(same)}x in {win}s (budget {tdef['max_per_window']})"); stepups.append("effect_budget")
                elif tdef.get("max_identical_per_window") is not None and len(ident) >= tdef["max_identical_per_window"]:
                    F("effect_budget", pts["effect_budget"], f"identical '{tool}' already executed {len(ident)}x in {win}s (budget {tdef['max_identical_per_window']})"); stepups.append("effect_budget")
            # E2 tainted sensitive flow: sensitive data read in a session that also read untrusted content, now flowing out
            if hard is None and tdef["class"] in ("send", "write", "fetch") and sess["conf"] >= 2 and sess["integ"] == 0:
                F("tainted_sensitive_flow", pts["tainted_sensitive_flow"], f"session holds sensitivity-{sess['conf']} data and untrusted influence; '{tool}' would move it")
                stepups.append("tainted_sensitive_flow")
            # E2 provenance: writes into a trusted store under untrusted influence are labelled untrusted (readers inherit taint)
            if hard is None and tdef.get("trusted_store") and sess["integ"] == 0:
                F("untrusted_provenance_write", pts["untrusted_provenance_write"], f"'{tool}' writes untrusted-influenced content into a trusted store; object will be labelled untrusted")
                provenance = True

        # ---- behavioural assessment (only ever makes the response stricter) ----
        ab, rb = self.agent_base[aid], self.role_base[role]
        cold = ab["n"] < cfg["cold_start_min_events"]
        base = rb if cold else ab
        if tdef is not None and tool in rdef["tools"]:
            ttools = rdef["tasks"].get(a["task"]) if a["task"] else None
            if ttools is not None and tool not in ttools:
                F("task_scope_deviation", pts["task_scope_deviation"], f"'{tool}' is in the role but not in active task '{a['task']}' {ttools}")
            p_tool = (base["tool"].get(tool, 0) + 0.5) / (base["n"] + 0.5 * len(rdef["tools"])) if base["n"] else 1 / len(rdef["tools"])
            if base["n"] and base["tool"].get(tool, 0) == 0:
                F("novel_tool", pts["novel_tool"], f"'{tool}' never observed in {'role' if cold else 'agent'} baseline")
            elif p_tool < cfg["rarity_floor_prob"]:
                F("rarity", min(pts["rarity_max"], round(-math.log2(p_tool))), f"p(tool)={p_tool:.3f} below floor")
            if tdef["class"] in ("send", "fetch") and base["n"] and base["dest"].get(dest, 0) == 0:
                F("novel_destination", pts["novel_destination"], f"destination '{dest}' never observed in baseline")
            if tdef.get("impact"):
                F("impact", pts["impact_per_level"] * tdef["impact"], f"impact level {tdef['impact']} ({tdef['class']})")
            if tdef["sensitivity"] >= 2:
                F("sensitivity", pts["sensitivity_per_level"] * tdef["sensitivity"], f"resource sensitivity {tdef['sensitivity']}")
        ts = self.times[aid]
        recent_n = sum(1 for t in ts if now - t <= cfg["rate_window_s"]) + 1   # including this action
        rmax = rdef.get("max_rate_per_min")
        if rmax is not None and recent_n > rmax * cfg["rate_window_s"] / 60:
            F("rate_spike", pts["rate_spike"], f"{recent_n} actions in {cfg['rate_window_s']}s exceeds the declared role ceiling {rmax}/min")
        elif len(ab["rates"]) >= 5:
            mu = sum(ab["rates"]) / len(ab["rates"]); sd = math.sqrt(sum((r - mu) ** 2 for r in ab["rates"]) / len(ab["rates"])) or 1.0
            if (recent_n - mu) / sd > cfg["rate_z"]:
                F("rate_spike", pts["rate_spike"], f"{recent_n} actions/{cfg['rate_window_s']}s vs baseline {mu:.1f}+-{sd:.1f}")
        rec = Counter(x["tool"] for x in self.recent[aid]); rec[tool] += 1
        ref = self.ref_tool.get(aid) if not cold else self.ref_tool.get("role:" + role)
        if sum(rec.values()) >= cfg["drift_window"] // 2 and ref:
            js = _js(_norm(rec), _norm(ref))
            if js > cfg["drift_js_threshold"]:
                F("distribution_drift", pts["distribution_drift"], f"recent tool mix diverges from baseline (JS={js:.2f} > {cfg['drift_js_threshold']})")
        if sum(self.recent_anom[aid]) >= cfg["repeat_count"]:
            F("repeated_anomalies", pts["repeated_anomalies"], f"{sum(self.recent_anom[aid])} anomalous actions in last {cfg['repeat_window']}")

        # E2 drift alert rule: deviation points over the last N actions (window cleared by declared task/role changes)
        dev_now = sum(f["points"] for f in factors if f["factor"] in DEVIATION)
        learned_now = sum(f["points"] for f in factors if f["factor"] in LEARNED_DEVIATION)
        win_sum = sum(d for d, _ in self.dev_window[aid]) + dev_now
        win_learned = sum(l for _, l in self.dev_window[aid]) + learned_now
        # role-aware rule: drift needs deviation from the declared task AND from learned behaviour (an agent repeating what it
        # has always done is not drifting, even outside the current task label)
        drift_state = win_sum >= cfg.get("drift_alert_points", 10 ** 9) and win_learned > 0
        if drift_state:
            F("drift_alert", 0, f"{win_sum} deviation points in the last {cfg.get('drift_alert_window')} actions >= {cfg.get('drift_alert_points')}")
        score = min(100, sum(f["points"] for f in factors))
        band = "HIGH" if score >= cfg["bands"]["high"] else "MEDIUM" if score >= cfg["bands"]["medium"] else "LOW"

        # ---- response ----
        quarantine = False
        if hard:
            response, reason = hard
            if hard[1] in ("out-of-role action", "sensitivity ceiling", "authority escalation beyond delegated scope", "destination not in mandate", "invalid delegation") and (consequential or (tdef and tdef["sensitivity"] >= 2) or sum(self.recent_anom[aid]) >= 1):
                quarantine = True
        elif cedar == "APPROVAL_REQUIRED" or stepups or (consequential and (band != "LOW" or drift_state)) or (a["status"] == "restricted" and consequential):
            response, reason = "APPROVAL_REQUIRED", ("policy P step-up" if cedar == "APPROVAL_REQUIRED" else
                                                     f"step-up: {stepups[0]}" if stepups else
                                                     "agent restricted" if a["status"] == "restricted" else
                                                     "drift alert" if drift_state and band == "LOW" else f"risk {band}")
        else:
            response, reason = "ALLOW", "within mandate" + (f" (risk {band}: monitored)" if band != "LOW" else "")
        if response == "APPROVAL_REQUIRED":
            grant = self._matching_approval(aid, tool, args, ev.get("approval_id"))
            if grant:
                response, reason = "ALLOW", f"owner approval {grant['id']} (one-time)"
                grant["status"] = "consumed"
        owner_approved = response == "ALLOW" and reason.startswith("owner approval")
        # drift accumulator: decayed sum of anomaly points; crossing the threshold quarantines (gradual drift)
        dev_points = sum(f["points"] for f in factors if f["factor"] in DEVIATION)
        anomalous = (dev_points > 0 or hard is not None) and not owner_approved   # an owner-approved action is vouched for
        self.accum[aid] = self.accum[aid] * cfg["accumulator_decay"] + (0 if owner_approved else dev_points)
        if self.accum[aid] >= cfg["quarantine_drift_accumulator"] and a["status"] != "quarantined":
            quarantine = True; reason += f"; drift accumulator {self.accum[aid]:.0f} >= {cfg['quarantine_drift_accumulator']}"
            if response == "ALLOW" and consequential:
                response = "DENY"
        if hard:
            control = "deterministic"
        elif response == "ALLOW":
            control = "approval_grant" if owner_approved else "none"
        elif cedar == "APPROVAL_REQUIRED":
            control = "policy_P"
        elif stepups:
            control = stepups[0]
        elif a["status"] == "restricted":
            control = "restricted"
        else:
            control = "behavioural"
        if quarantine and not hard:
            control = "behavioural_quarantine"
        return self._finish(ev, now, a, response, factors, reason, factors, quarantine, score=score, band=band, cold=cold,
                            expected=expected, dlg=dlg, anomalous=anomalous, cedar=cedar, control=control, drift_state=drift_state,
                            dev_now=0 if owner_approved else dev_now, provenance=provenance, owner_approved=owner_approved,
                            learned_now=0 if owner_approved else learned_now)

    def _matching_approval(self, aid, tool, args, approval_id):
        h = hashlib.sha256(json.dumps([aid, tool, args], sort_keys=True).encode()).hexdigest()
        for ap in self.approvals.values():
            if ap["status"] == "approved" and ap["args_hash"] == h and (approval_id in (None, ap["id"])):
                return ap
        return None

    def _finish(self, ev, now, a, response, _f, reason, factors, quarantine, score=100, band="HIGH", cold=True, expected=None, dlg=None,
                anomalous=True, cedar=None, control="deterministic", drift_state=False, dev_now=0, provenance=False, owner_approved=False,
                learned_now=0):
        aid, tool = ev["agent_id"], ev["tool"]; args = dict(ev.get("args") or {})
        did = "dec-" + uuid.uuid4().hex[:10]
        rec = {"decision_id": did, "ts": now, "agent_id": aid, "role": a and a["role"], "task": a and a["task"], "tool": tool, "args": args,
               "destination": ev.get("destination") or "internal", "delegation": dlg and {"id": dlg["id"], "chain": dlg["chain"], "root": dlg["root"]},
               "response": response, "reason": reason, "risk_score": score, "risk_band": band,
               "confidence": "low (cold start: role prior)" if cold else "normal", "factors": factors, "expected_authority": expected,
               "cedar": cedar, "observed_by": ev.get("observed_by", "engine"), "control": control, "drift_alert": drift_state}
        if a is not None:
            if response == "APPROVAL_REQUIRED":
                ap_id = "apr-" + uuid.uuid4().hex[:8]
                self.approvals[ap_id] = {"id": ap_id, "agent_id": aid, "tool": tool, "args": args, "decision_id": did, "risk_score": score,
                                         "reason": reason, "factors": factors, "status": "pending", "created": now,
                                         "args_hash": hashlib.sha256(json.dumps([aid, tool, args], sort_keys=True).encode()).hexdigest()}
                rec["approval_id"] = ap_id
            if quarantine and a["status"] != "quarantined":
                self.set_status(aid, "quarantined", f"automatic: {reason}", by="engine")
                rec["agent_status_change"] = "quarantined"
            elif response == "DENY" and a["status"] == "active" and band == "HIGH":
                self.set_status(aid, "restricted", f"automatic: {reason}", by="engine")
                rec["agent_status_change"] = "restricted"
            self.recent_anom[aid].append(1 if anomalous else 0)
            self.dev_window[aid].append((dev_now, learned_now))
            self.times[aid].append(now)
            self.recent[aid].append({"tool": tool, "ts": now})
            tdef = self.tools.get(tool)
            if response == "ALLOW" and tdef:
                s = self.session[aid]
                self.effects[aid].append((now, tool, hashlib.sha256(json.dumps([tool, args], sort_keys=True).encode()).hexdigest()))
                key = args.get("title") or args.get("page")
                if tdef.get("trusted_store") and key is not None:
                    self.store_labels[(tdef["resource"], str(key))] = "untrusted" if provenance else "trusted"
                    rec["provenance_label"] = self.store_labels[(tdef["resource"], str(key))]
                if tdef.get("reads_store") and self.store_labels.get((tdef["reads_store"], str(key))) == "untrusted":
                    s["integ"] = 0; rec["provenance_label"] = "untrusted (inherited)"
                if tdef["class"] in ("read", "fetch"):
                    s["conf"] = max(s["conf"], tdef["sensitivity"])
                    if tdef.get("source") == "untrusted":
                        s["integ"] = 0
                    else:
                        s["trusted_text"] += " " + json.dumps(ev.get("output", ""))[:2000].lower()
                if score <= self.cfg["baseline_update_max_risk"] and not anomalous and not owner_approved:   # anti-poisoning: never learn from approved/risky actions
                    b = self.agent_base[aid]; b["tool"][tool] += 1; b["dest"][rec["destination"]] += 1; b["n"] += 1
                    a["history_n"] = b["n"]
        if owner_approved:
            self.audit.append({"kind": "approved_action_not_learned", "decision_id": did, "agent": aid, "tool": tool})
        if band != "LOW" or response != "ALLOW" or drift_state:
            alert = {"alert_id": "alr-" + uuid.uuid4().hex[:8], "decision_id": did, "ts": now, "agent_id": aid, "tool": tool,
                     "severity": band if (band != "LOW" or not drift_state) else "DRIFT", "risk_score": score, "response": response,
                     "reason": reason, "factors": factors, "control": control,
                     "confidence": rec["confidence"], "expected_authority": expected, "status": "open"}
            self.alerts.append(alert); rec["alert_id"] = alert["alert_id"]
        self.events.append(rec)
        self.audit.append({"kind": "decision", **{k: rec[k] for k in ("decision_id", "agent_id", "role", "task", "tool", "args", "destination",
                                                                       "delegation", "response", "reason", "risk_score", "risk_band", "confidence",
                                                                       "factors", "expected_authority")}})
        return rec

    def record_rates(self, agent_id, counts):
        """Per-window action counts from the benign baseline period (rate baseline)."""
        self.agent_base[agent_id]["rates"].extend(counts)
