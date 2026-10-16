"""MANDATE behavioural-drift engine, version E4 (E3 is preserved unchanged in mandate/engine_e3.py, tag engine-E3).
E4 closes the E3 residuals: (Y1) HR objects and recipients are authorized ONLY by the trusted, structured task scope
declared by the owner (subjects / requester), never by names parsed from instruction text; HR data may not be sent to
a non-subject (DENY). (Y2) cumulative read limits over 10 min / 1 h / 24 h plus distinct-object budgets per day and
week. (Y3) the same budgets are also enforced on a shared pool keyed by (root principal, protected dataset), so
parallel or delegated agents and freshly registered agent ids cannot reset them; owner-declared multi-agent tasks
size the pool explicitly (task_meta.pool_agents). Read counters and spend are rebuilt from the hash-chained audit log
at start-up (a restart does not reset them; a broken chain refuses to start).

E3 description follows.
MANDATE behavioural-drift engine, version E3 (E1/E2 remain in mandate/engine.py history: tags engine-E1, engine-E2).
E3 adds: typed exact grounding (numbers parsed to Decimal; money distinguished from quantities; ambiguity -> step-up;
word-boundary string matching), cumulative per-task spend limits, object/field/purpose authorization with recipient
checks, role- and task-aware read-volume enforcement over rolling windows (all read tools combined, distinct
sensitive objects), rate-ceiling enforcement on reads, auditable read-budget extensions, and alerts on provenance-
labelled writes.

Original E2 description follows.
MANDATE behavioural-drift engine (prototype).

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
import copy, fnmatch, hashlib, json, math, re, threading, time, uuid
from decimal import Decimal, InvalidOperation
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


MONEY_RE = re.compile(r"(?:(?:amount|budget|total|price|cost|spend|for|of)\s*(?:of\s*)?|[$\u20ac\u00a3]\s*)(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:usd|eur|gbp|dollars?)\b", re.I)
NUM_RE = re.compile(r"(?<![\w.])[$\u20ac\u00a3]?(\d[\d,]*(?:\.\d+)?)(?![\w])")


def _dec(x):
    try:
        return Decimal(str(x).replace(",", "").replace("$", "").replace("\u20ac", "").replace("\u00a3", "").strip())
    except (InvalidOperation, ValueError):
        return None


def money_values(text):
    """Distinct money amounts in text (Decimal), e.g. 'amount 900', '$1,200.00', '1200 usd'."""
    out = set()
    for m in MONEY_RE.finditer(text or ""):
        d = _dec(m.group(1) or m.group(2))
        if d is not None:
            out.add(d.normalize())
    return out


def number_values(text):
    return {d.normalize() for d in (_dec(m.group(1)) for m in NUM_RE.finditer(text or "")) if d is not None}


def ground_value(key, v, instruction, trusted):
    """Typed exact grounding. Returns 'grounded' | 'ambiguous' | 'ungrounded'.
    Money keys (amount/price/total) must equal exactly one distinct money value in the task instruction (several distinct
    money values -> ambiguous) or appear as a money value in trusted output. Other numbers: exact Decimal equality.
    Strings: whole-token match (word boundaries), never substring."""
    d = _dec(v) if not isinstance(v, bool) else None
    if d is not None and not (isinstance(v, str) and not re.fullmatch(r"[$\u20ac\u00a3]?\s*\d[\d,]*(?:\.\d+)?", v.strip())):
        d = d.normalize()
        if key in ("amount", "price", "total"):
            mi = money_values(instruction)
            if d in mi:
                return "ambiguous" if len(mi) > 1 else "grounded"
            return "grounded" if d in money_values(trusted) else "ungrounded"
        return "grounded" if d in number_values(instruction) | number_values(trusted) else "ungrounded"
    s = str(v).strip().lower()
    if not s:
        return "grounded"
    pat = r"(?<![\w@.-])" + re.escape(s) + r"(?![\w@-])"
    return "grounded" if re.search(pat, (instruction or "").lower()) or re.search(pat, (trusted or "").lower()) else "ungrounded"


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
        self.cat = json.loads(Path(roles_path or ROOT / "config" / "roles_e4.json").read_text(encoding="utf-8"))
        self.cfg = json.loads(Path(config_path or ROOT / "config" / "engine_config_e4.json").read_text(encoding="utf-8"))
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
        self.reads = defaultdict(lambda: deque(maxlen=5000))           # E3: (ts, object_key, sensitivity) per agent; NOT reset by task changes
        self.read_attempts = defaultdict(lambda: deque(maxlen=5000))   # E3: every read decision (incl. gated) -> escalation on hammering
        self.spend = defaultdict(lambda: Decimal(0))                   # E3: executed spend per (agent, task epoch)
        self.read_ext = defaultdict(int)                               # E3: owner-granted read-budget extensions per agent
        self.task_epoch = defaultdict(int)
        self.pool_reads = defaultdict(lambda: deque(maxlen=20000))    # E4: (ts, object_key) per (principal, dataset)
        self.audit = AuditLog(audit_path)
        self._rehydrate()
        pdir = Path(policy_dir or ROOT.parent / "S2-cedar" / "config")
        self.P = PolicySet.from_str((pdir / "policies_P.cedar").read_text()) if HAVE_CEDAR else None
        self.S = Schema.from_str((pdir / "schema.cedarschema").read_text()) if HAVE_CEDAR else None

    def _rehydrate(self):
        """E4: rebuild cumulative read and spend counters from the audit log so a restart cannot reset them."""
        if not self.audit.records:
            return
        if not self.audit.verify()["ok"]:
            raise RuntimeError("audit chain broken: refusing to start with unverifiable cumulative counters")
        for r in self.audit.records:
            e = r["entry"]
            if e.get("kind") != "decision" or e.get("response") != "ALLOW" or e.get("ts") is None:
                continue
            if e.get("read_key"):
                self.reads[e["agent_id"]].append((e["ts"], e["read_key"], e.get("read_sens", 0)))
                if e.get("pool"):
                    self.pool_reads[tuple(e["pool"])].append((e["ts"], e["read_key"]))
            if e.get("spend") is not None:
                self.spend[(e["agent_id"], e.get("epoch", 0))] += Decimal(str(e["spend"]))
        self.audit.append({"kind": "counters_rehydrated", "reads": sum(len(v) for v in self.reads.values()),
                           "pools": len(self.pool_reads)})

    def _principal(self, aid):
        """Root principal: the owner at the root of a delegation chain the agent is a child in, else its own owner."""
        for d in self.delegations.values():
            if d["child"] == aid:
                return d["root"]
        return self.agents[aid]["owner"]

    @staticmethod
    def _read_key(tool, tdef, args):
        return f"{tool}:{args.get(tdef.get('object_arg') or 'item') or args.get('page') or args.get('doc') or args.get('url') or ''}"

    # ------------------------------------------------------------------ registry / owner actions
    def register_agent(self, agent_id, role, owner="owner", task=None, instruction="", subjects=None, requester=None):
        with self.lock:
            if role not in self.roles:
                raise ValueError(f"unknown role {role}")
            self.agents[agent_id] = {"agent_id": agent_id, "role": role, "status": "active", "task": task, "task_instruction": instruction,
                                     "subjects": [s.lower() for s in (subjects or ([requester] if requester else []))], "requester": requester,
                                     "owner": owner, "created": self.clock(), "history_n": self.agent_base[agent_id]["n"]}
            self.audit.append({"kind": "agent_registered", "agent": agent_id, "role": role, "owner": owner, "task": task})
            return self.agents[agent_id]

    def assign_task(self, agent_id, task, instruction="", by="owner", subjects=None, requester=None):
        """Owner-authorized, legitimate task change: the active scope moves; it is not drift."""
        with self.lock:
            a = self.agents[agent_id]
            if task not in self.roles[a["role"]]["tasks"]:
                raise ValueError(f"task {task} not defined for role {a['role']}")
            old = a["task"]; a["task"], a["task_instruction"] = task, instruction
            a["subjects"] = [s.lower() for s in (subjects or ([requester] if requester else []))]; a["requester"] = requester
            self.task_epoch[agent_id] += 1
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
        tmeta = (rdef.get("task_meta") or {}).get(a["task"] or "", {})
        subjects = a.get("subjects") or []
        def is_subject(x):   # E4: ONLY the owner-declared structured scope; instruction text never authorizes an HR object
            x = str(x).strip().lower()
            return bool(x) and x not in ("all", "*") and x in subjects
        # E3 object-level / field-level / purpose authorization
        if hard is None and tdef.get("object_arg"):
            obj = str(args.get(tdef["object_arg"], "")).strip().lower()
            if not tmeta.get("bulk") and not is_subject(obj):
                F("object_authorization", pts["object_authorization"], f"{tdef['object_arg']}='{obj or '?'}' is not a subject of task '{a['task']}' (subjects {subjects}); purpose: {tmeta.get('purpose', 'undeclared')}")
                hard = ("DENY", "object not authorized for this task's purpose")
            fa = tdef.get("field_arg")
            allowed = tmeta.get("fields", ["all"])
            if hard is None and fa and "all" not in allowed:
                req = [f.strip().lower() for f in str(args.get(fa, "all")).split(",")]
                if "all" in req or any(f not in allowed for f in req):
                    F("field_authorization", pts["field_authorization"], f"fields {req} exceed purpose fields {allowed}")
                    hard = ("DENY", "fields not authorized for this task's purpose")
        if hard is not None and hard[1] in ("object not authorized for this task's purpose", "fields not authorized for this task's purpose"):
            sess["authz_violation"] = True
        if hard is None and sess.get("authz_violation") and tdef["class"] in ("send", "write", "fetch"):
            F("after_authz_violation", pts["after_authz_violation"], "this session already attempted an unauthorized object/field access; consequential actions need approval")
            stepups.append("after_authz_violation")
        to_subject = False
        if hard is None and role == "hr_assistant" and tdef["class"] == "send" and sess["conf"] >= 2:
            to = str(args.get("to", "")).strip().lower()
            to_subject = is_subject(to) and not sess.get("authz_violation")
            if not is_subject(to):
                F("recipient_not_subject", pts["recipient_not_subject"], f"HR data in session; recipient '{to}' is not a declared task subject {subjects}")
                hard = ("DENY", "recipient not authorized for HR data")
        if hard is None and tdef.get("spend_arg"):
            amt = _dec(args.get(tdef["spend_arg"]))
            auth = money_values(a.get("task_instruction"))
            key = (aid, self.task_epoch[aid])
            if amt is not None and len(auth) == 1:
                limit = next(iter(auth))
                if self.spend[key] + amt > limit:
                    F("spend_limit", pts["spend_limit"], f"cumulative spend {self.spend[key] + amt} would exceed the task's authorized amount {limit}")
                    hard = ("DENY", "cumulative spend limit exceeded")
        # E3 read-volume enforcement (all read/fetch tools combined; rolling windows; not reset by task changes)
        if hard is None and tdef["class"] in ("read", "fetch"):
            bud = dict(rdef.get("read_budget") or {}); bud.update(tmeta.get("read_budget") or {})
            ext = self.read_ext[aid]
            okey = f"{tool}:{args.get(tdef.get('object_arg') or 'item') or args.get('page') or args.get('doc') or args.get('url') or ''}"
            rs = self.reads[aid]
            okey = self._read_key(tool, tdef, args)
            pool = (self._principal(aid), tdef["resource"]); pr = self.pool_reads[pool]
            psize = max(1, int(tmeta.get("pool_agents") or 1))
            for win, cap in ((86400, bud.get("distinct_per_day")), (604800, bud.get("distinct_per_week"))):
                if cap is not None and "read_volume" not in stepups:
                    d_agent = len({k for t0, k, _ in rs if now - t0 <= win} | {okey})
                    d_pool = len({k for t0, k in pr if now - t0 <= win} | {okey})
                    if d_agent > cap + ext or d_pool > cap * psize + ext:
                        F("read_volume", pts["read_volume"], f"distinct objects in {win}s: agent {d_agent}, pool {d_pool} > budget {cap} (pool x{psize})")
                        stepups.append("read_volume")
            for win, cap in ((600, bud.get("per_600s")), (3600, bud.get("per_3600s")), (86400, bud.get("per_86400s"))):
                if cap is not None and "read_volume" not in stepups:
                    n_pool = sum(1 for t0, _ in pr if now - t0 <= win) + 1
                    if n_pool > cap * psize + ext:
                        F("read_volume", pts["read_volume"], f"{n_pool} reads in {win}s on shared pool {list(pool)} > {cap} x{psize} agents")
                        stepups.append("read_volume")
            for win, cap in ((600, bud.get("per_600s")), (3600, bud.get("per_3600s")), (86400, bud.get("per_86400s"))):
                if cap is None:
                    continue
                n = sum(1 for t0, _, _ in rs if now - t0 <= win) + 1
                n_att = sum(1 for t0 in self.read_attempts[aid] if now - t0 <= win) + 1
                cap_eff = cap + ext
                if n_att > cap_eff * cfg.get("read_volume_hard_multiplier", 2.0):
                    F("read_volume", pts["read_volume"], f"{n_att} read attempts in {win}s > {cfg.get('read_volume_hard_multiplier')}x budget {cap_eff} (hammering after the gate)")
                    hard = ("DENY", "read volume far beyond the task budget"); break
                if n > cap_eff:
                    F("read_volume", pts["read_volume"], f"{n} reads in {win}s exceed the task budget {cap_eff} (declared batch tasks raise it)")
                    stepups.append("read_volume"); break
            if hard is None and tdef["sensitivity"] >= 2 and bud.get("sensitive_unique") is not None:
                uniq = {k for t0, k, s in rs if s >= 2 and now - t0 <= 3600} | {okey}
                if len(uniq) > bud["sensitive_unique"]:
                    F("sensitive_breadth", pts["sensitive_breadth"], f"{len(uniq)} distinct sensitive objects in 1h > {bud['sensitive_unique']}")
                    stepups.append("read_volume")
        if hard is None and consequential:
            cons = [x for k in tdef.get("consequential", []) for x in _vals(args.get(k))]
            gres = {k: [ground_value(k, x, a.get("task_instruction") or "", sess["trusted_text"]) for x in _vals(args.get(k))]
                    for k in tdef.get("consequential", [])}
            grounded = all(g == "grounded" for gs in gres.values() for g in gs)
            if any(g == "ambiguous" for gs in gres.values() for g in gs):
                F("ambiguous_amount", pts["ambiguous_amount"], f"amount matches one of several money values in the instruction {sorted(map(str, money_values(a.get('task_instruction'))))}")
                stepups.append("numeric_grounding")
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
            # E3: exempt only an HR reply to the task's own subject/requester (recipient fixed by the trusted instruction)
            if hard is None and tdef["class"] in ("send", "write", "fetch") and sess["conf"] >= 2 and sess["integ"] == 0 and not to_subject:
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
        rmax = None if (tmeta.get("read_budget")) else rdef.get("max_rate_per_min")   # an owner-declared batch sets its own rate expectation
        if rmax is not None and recent_n > rmax * cfg["rate_window_s"] / 60:
            F("rate_spike", pts["rate_spike"], f"{recent_n} actions in {cfg['rate_window_s']}s exceeds the declared role ceiling {rmax}/min")
            if tdef is not None and tdef["class"] in ("read", "fetch") and not (tmeta.get("read_budget")):
                stepups.append("rate_ceiling")   # E3: enforced, not only alerted (declared batch tasks are exempt)
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
        if response == "APPROVAL_REQUIRED" and stepups and set(stepups) <= {"read_volume", "rate_ceiling"}:
            grant = self._matching_approval(aid, "__read_budget__", {}, None)
            if grant:
                grant["status"] = "consumed"; self.read_ext[aid] += cfg.get("read_budget_extension", 40)
                response, reason = "ALLOW", f"owner approval {grant['id']} extended the read budget by {cfg.get('read_budget_extension', 40)}"
                self.audit.append({"kind": "read_budget_extended", "agent": aid, "by_approval": grant["id"], "extension_total": self.read_ext[aid]})
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
            control = {"object not authorized for this task's purpose": "object_authorization",
                       "fields not authorized for this task's purpose": "field_authorization",
                       "cumulative spend limit exceeded": "spend_limit",
                       "read volume far beyond the task budget": "read_volume",
                       "recipient not authorized for HR data": "recipient_authorization"}.get(hard[1], "deterministic")
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
                rb_kind = control in ("read_volume", "rate_ceiling")
                self.approvals[ap_id] = {"id": ap_id, "agent_id": aid, "tool": tool, "args": args, "decision_id": did, "risk_score": score,
                                         "reason": reason, "factors": factors, "status": "pending", "created": now,
                                         "kind": "read_budget_extension" if rb_kind else "action",
                                         "args_hash": hashlib.sha256(json.dumps([aid, "__read_budget__", {}] if rb_kind else [aid, tool, args], sort_keys=True).encode()).hexdigest()}
                rec["approval_id"] = ap_id
            if quarantine and a["status"] != "quarantined":
                self.set_status(aid, "quarantined", f"automatic: {reason}", by="engine")
                rec["agent_status_change"] = "quarantined"
            elif response == "DENY" and a["status"] == "active" and (band == "HIGH" or control == "read_volume"):
                self.set_status(aid, "restricted", f"automatic: {reason}", by="engine")
                rec["agent_status_change"] = "restricted"
            self.recent_anom[aid].append(1 if anomalous else 0)
            self.dev_window[aid].append((dev_now, learned_now))
            self.times[aid].append(now)
            _td = self.tools.get(tool)
            if _td is not None and _td["class"] in ("read", "fetch"):
                self.read_attempts[aid].append(now)
            self.recent[aid].append({"tool": tool, "ts": now})
            tdef = self.tools.get(tool)
            if response == "ALLOW" and tdef:
                s = self.session[aid]
                self.effects[aid].append((now, tool, hashlib.sha256(json.dumps([tool, args], sort_keys=True).encode()).hexdigest()))
                if tdef["class"] in ("read", "fetch"):
                    ok_ = self._read_key(tool, tdef, args)
                    self.reads[aid].append((now, ok_, tdef["sensitivity"]))
                    pool = (self._principal(aid), tdef["resource"]); self.pool_reads[pool].append((now, ok_))
                    rec["read_key"], rec["read_sens"], rec["pool"] = ok_, tdef["sensitivity"], list(pool)
                if tdef.get("spend_arg") and _dec(args.get(tdef["spend_arg"])) is not None:
                    self.spend[(aid, self.task_epoch[aid])] += _dec(args.get(tdef["spend_arg"]))
                    rec["spend"], rec["epoch"] = str(_dec(args.get(tdef["spend_arg"]))), self.task_epoch[aid]
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
        if band != "LOW" or response != "ALLOW" or drift_state or provenance:
            alert = {"alert_id": "alr-" + uuid.uuid4().hex[:8], "decision_id": did, "ts": now, "agent_id": aid, "tool": tool,
                     "severity": band if (band != "LOW" or not drift_state) else "DRIFT", "risk_score": score, "response": response,
                     "reason": reason, "factors": factors, "control": control,
                     "confidence": rec["confidence"], "expected_authority": expected, "status": "open"}
            self.alerts.append(alert); rec["alert_id"] = alert["alert_id"]
        self.events.append(rec)
        self.audit.append({"kind": "decision", **{k: rec[k] for k in ("decision_id", "agent_id", "role", "task", "tool", "args", "destination",
                                                                       "delegation", "response", "reason", "risk_score", "risk_band", "confidence",
                                                                       "factors", "expected_authority")},
                                           "ts": now, **{k: rec[k] for k in ("read_key", "read_sens", "pool", "spend", "epoch") if k in rec}})
        return rec

    def record_rates(self, agent_id, counts):
        """Per-window action counts from the benign baseline period (rate baseline)."""
        self.agent_base[agent_id]["rates"].extend(counts)
