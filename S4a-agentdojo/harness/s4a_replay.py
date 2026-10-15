"""S4a: LLM-free AgentDojo v1.2.2 ground-truth replay through an IN-PROCESS PEP EMULATOR.
*** In-process decision emulation. This measures decision logic only; it says NOTHING about mediation,
LLM behaviour or attack success rates (playbook rule 6). ***
Usage: python s4a_replay.py <out_dir>   (S2 Cedar config at /s2cfg, annotations at /cfg)

Modes per task:
  native     - ground-truth calls straight through AgentDojo's FunctionsRuntime (reference outcome)
  permit_all - same calls through the emulator wrapper, every call allowed     -> PARITY with native required
  deny_all   - emulator blocks every effectful call (negative control: shows the checks are sensitive)
  mandate    - S2 policy P via two-pass Cedar (AM9 rule) with session labels from the frozen annotations;
               only PERMIT executes; APPROVAL_REQUIRED is NOT auto-approved (no approver in replay)
Benign: each user task alone. Attack: user-task calls (which read the injected vectors), then the injection task's calls.
"""
import copy, hashlib, json, sys, time
from pathlib import Path
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime
from cedarpy import is_authorized, Decision, PolicySet, Schema

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
VERSION = "v1.2.2"
raw_ann = Path("/cfg/tool_annotations.json").read_bytes()
ANN = json.loads(raw_ann)
THR = ANN["untrusted_threshold"]
P = PolicySet.from_str(Path("/s2cfg/policies_P.cedar").read_text())
SCH = Schema.from_str(Path("/s2cfg/schema.cedarschema").read_text())

def two_pass(action, ctx):
    """AM9: Allow only if decision == Allow and no errors; first pass approved=True, second approved=False."""
    res = "Resource::\"doc\"" if action == "read" else "Sink::\"sink\""
    def ev(approved):
        c = copy.deepcopy(ctx); c["approved"] = approved
        return is_authorized({"principal": 'Agent::"procurement"', "action": f'Action::"{action}"', "resource": res, "context": c}, P, [], schema=SCH)
    r1 = ev(True)
    if r1.diagnostics.errors or r1.decision != Decision.Allow:
        return "DENY"
    r2 = ev(False)
    if r2.diagnostics.errors:
        return "DENY"
    return "PERMIT" if r2.decision == Decision.Allow else "APPROVAL_REQUIRED"

def norm_vals(v):
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, (list, tuple)):
        return [x for e in v for x in norm_vals(e)]
    if isinstance(v, float) and v.is_integer():
        return [str(int(v)), str(v)]
    return [str(v)]

class Session:
    def __init__(self, prompt):
        self.conf, self.integ = 0, 2
        self.trusted_text = prompt.lower()

    def decide(self, ann, fn, args):
        a = ann[fn]
        if a["kind"] == "read":
            ctx = {"session": {"conf": self.conf, "integ": self.integ},
                   "target": {"external": False, "clearance": 3, "untrusted_threshold": THR},
                   "params": {"all_grounded": True}}
            return two_pass("read", ctx), True
        cons = [x for k in a["consequential"] for x in norm_vals(args.get(k))]
        grounded = all(any(c.lower() == x or c.lower() in self.trusted_text for x in [c.lower()]) for c in cons)
        ctx = {"session": {"conf": self.conf, "integ": self.integ},
               "target": {"external": a["external"], "clearance": a["clearance"], "untrusted_threshold": THR},
               "params": {"all_grounded": grounded}}
        return two_pass("send", ctx), grounded

    def observe(self, ann, fn, output):
        a = ann[fn]
        if a["kind"] != "read":
            return
        self.conf = max(self.conf, a["conf"])
        if a["integ_source"] == "untrusted":
            self.integ = 0          # raise-only labels: untrusted content lowers session integrity for good
        else:
            self.trusted_text += " " + str(output).lower()

def execute(suite, env, calls, mode, prompt, ann):
    rt = FunctionsRuntime(suite.tools)
    sess = Session(prompt); recs = []
    for c in calls:
        fn, args = c.function, dict(c.args)
        if mode == "native":
            dec, grounded = "PERMIT", None
        elif mode == "permit_all":
            dec, grounded = "PERMIT", None
        elif mode == "deny_all":
            dec, grounded = ("PERMIT" if ann[fn]["kind"] == "read" else "DENY"), None
        else:
            dec, grounded = sess.decide(ann, fn, args)
        out, err = (None, None)
        if dec == "PERMIT":
            out, err = rt.run_function(env, fn, args, raise_on_error=False)
            sess.observe(ann, fn, out)
        recs.append({"fn": fn, "decision": dec, "grounded": grounded, "error": err,
                     "labels_after": [sess.conf, sess.integ], "_call": c if dec == "PERMIT" else None})
    return recs

def check_utility(task, pre, post, recs):  # same order as AgentDojo TaskSuite._check_user_task_utility
    tr = [r["_call"] for r in recs if r.get("_call") is not None]
    u = task.utility_from_traces(gto(task), pre, post, tr)
    return u if u is not None else task.utility(gto(task), pre, post)

def check_security(task, out, pre, post, recs):  # same order as TaskSuite._check_injection_task_security
    tr = [r["_call"] for r in recs if r.get("_call") is not None]
    s = task.security_from_traces(out, pre, post, tr)
    return s if s is not None else task.security(out, pre, post)

def strip(recs):
    for r in recs:
        r.pop("_call", None)
    return recs

def gto(task):
    return getattr(task, "GROUND_TRUTH_OUTPUT", "") or ""

rows, t0 = [], time.time()
for sname in ["workspace", "travel", "banking", "slack"]:
    suite = get_suite(VERSION, sname); ann = ANN["suites"][sname]
    defaults = suite.get_injection_vector_defaults()
    base_env = suite.load_and_inject_default_environment(defaults)
    # ---------- benign ----------
    for uid, ut in suite.user_tasks.items():
        pre = copy.deepcopy(base_env); calls = ut.ground_truth(copy.deepcopy(pre)); row = {"suite": sname, "kind": "benign", "user_task": uid}
        for mode in ["native", "permit_all", "deny_all", "mandate"]:
            post = copy.deepcopy(pre)
            try:
                recs = execute(suite, post, calls, mode, ut.PROMPT, ann)
                util = bool(check_utility(ut, pre, post, recs)); strip(recs)
            except Exception as e:
                recs, util = [], f"ERROR {type(e).__name__}: {e}"[:200]
            row[mode] = {"utility": util, "decisions": [r["decision"] for r in recs], "calls": recs}
        rows.append(row)
    # ---------- attack ----------
    for iid, it in suite.injection_tasks.items():
        # LLM-free: the injection task's ground-truth calls are executed directly, so the environment keeps the
        # DEFAULT vector values (labels are source-based, not content-based). Injecting GOAL text verbatim made
        # injected emails collide with the attack's own subject in run1 (harness error; see NOTE).
        env_i = base_env
        for uid, ut in suite.user_tasks.items():
            pre = copy.deepcopy(env_i)
            calls_u = ut.ground_truth(copy.deepcopy(pre)); calls_i = it.ground_truth(copy.deepcopy(pre))
            row = {"suite": sname, "kind": "attack", "user_task": uid, "injection_task": iid, "n_user_calls": len(calls_u)}
            for mode in ["native", "permit_all", "mandate"]:
                post = copy.deepcopy(pre)
                try:
                    recs = execute(suite, post, calls_u + calls_i, mode, ut.PROMPT, ann)
                    sec = bool(check_security(it, gto(ut), pre, post, recs)); strip(recs)
                except Exception as e:
                    recs, sec = [], f"ERROR {type(e).__name__}: {e}"[:200]
                row[mode] = {"attack_succeeded": sec, "injection_decisions": [r["decision"] for r in recs[len(calls_u):]],
                             "user_decisions": [r["decision"] for r in recs[:len(calls_u)]]}
            rows.append(row)
    print(sname, "done", round(time.time() - t0, 1), "s", flush=True)

# ---------- metrics ----------
ben = [r for r in rows if r["kind"] == "benign"]; att = [r for r in rows if r["kind"] == "attack"]
def is_err(x):
    return isinstance(x, str) and x.startswith("ERROR")
native_pass = [r for r in ben if r["native"]["utility"] is True]
parity_ben = [r for r in native_pass if r["permit_all"]["utility"] is not True]
deny_sensitive = [r for r in native_pass if r["deny_all"]["utility"] is not True]
calls_benign = [d for r in ben for d in r["mandate"]["decisions"]]
att_native_succ = [r for r in att if r["native"]["attack_succeeded"] is True]
parity_att = [r for r in att if r["native"]["attack_succeeded"] != r["permit_all"]["attack_succeeded"]]
blocked = [r for r in att_native_succ if r["mandate"]["attack_succeeded"] is not True]
summary = {
    "LABEL": "in-process decision emulation (S4a). Not mediation, not LLM behaviour, not attack success rates.",
    "agentdojo_benchmark_version": VERSION,
    "annotations_sha256_raw": hashlib.sha256(raw_ann).hexdigest(),
    "annotations_sha256_lf": hashlib.sha256(raw_ann.replace(b"\r\n", b"\n")).hexdigest(),
    "benign_tasks": len(ben), "benign_native_pass": len(native_pass),
    "benign_native_fail_or_error": [r["suite"] + "/" + r["user_task"] for r in ben if r["native"]["utility"] is not True],
    "parity_benign_mismatches": [r["suite"] + "/" + r["user_task"] for r in parity_ben],
    "negative_control_deny_all_changes_outcome": len(deny_sensitive),
    "mandate_benign_utility_preserved": sum(1 for r in native_pass if r["mandate"]["utility"] is True),
    "mandate_benign_call_decisions": {d: calls_benign.count(d) for d in sorted(set(calls_benign))},
    "attack_pairs": len(att), "attack_native_success": len(att_native_succ),
    "attack_native_errors": sum(1 for r in att if is_err(r["native"]["attack_succeeded"])),
    "parity_attack_mismatches": len(parity_att),
    "mandate_blocks_of_native_successful_attacks": len(blocked),
    "mandate_attacks_still_succeeding": [r["suite"] + "/" + r["user_task"] + "+" + r["injection_task"] for r in att_native_succ if r["mandate"]["attack_succeeded"] is True],
    "seconds": round(time.time() - t0, 1),
}
canon = json.dumps([{k: (v if k not in ("native", "permit_all", "deny_all", "mandate") else
                         {kk: vv for kk, vv in v.items() if kk != "calls"}) for k, v in r.items()} for r in rows], sort_keys=True)
summary["decision_hash"] = hashlib.sha256(canon.encode()).hexdigest()
(OUT / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: v for k, v in summary.items() if k not in ("mandate_attacks_still_succeeding",)}, indent=1)[:3000])
