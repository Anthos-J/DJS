"""S4a v2 replay (Wave 6). *** IN-PROCESS DECISION EMULATION: not mediation, not LLM behaviour, not attack rates. ***
Differences from s4a_replay.py (kept unchanged as the historical harness):
  1. FIXED grounding: a consequential value is grounded iff it occurs in the user prompt or in an earlier TRUSTED
     tool output (v1 had an always-true expression, so G2 never fired). A self-test runs first and aborts on failure.
  2. Evaluates several policy configurations in one deterministic run:
       baseline  = frozen P (S2) + frozen v1 annotations
       candidate = P2 (config/v2) + v2 annotations ; context adds params.prompt_grounded (values in the user prompt)
  3. Annotation kind 'fetch' = outbound request (decided like an external send on its consequential args) whose
     response is then labelled like an untrusted read.
Usage: python s4a_replay_v2.py <out_dir>  (mounts: /cfg = S4a config, /s2cfg = S2 config)"""
import copy, hashlib, json, sys, time
from pathlib import Path
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime
from cedarpy import is_authorized, Decision, PolicySet, Schema

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
VERSION = "v1.2.2"
CONFIGS = {
    "baseline": {"policy": "/s2cfg/policies_P.cedar", "schema": "/s2cfg/schema.cedarschema", "ann": "/cfg/tool_annotations.json", "v2ctx": False},
    "candidate": {"policy": "/cfg/v2/policies_P2.cedar", "schema": "/cfg/v2/schema_v2.cedarschema", "ann": "/cfg/v2/tool_annotations_v2.json", "v2ctx": True},
}
LOADED = {}
for name, c in CONFIGS.items():
    raw = {k: Path(c[k]).read_bytes() for k in ("policy", "schema", "ann")}
    LOADED[name] = {"P": PolicySet.from_str(raw["policy"].decode()), "S": Schema.from_str(raw["schema"].decode()),
                    "ANN": json.loads(raw["ann"]), "v2ctx": c["v2ctx"],
                    "sha256": {k: hashlib.sha256(v.replace(b"\r\n", b"\n")).hexdigest() for k, v in raw.items()}}

def norm_vals(v):
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, (list, tuple)):
        return [x for e in v for x in norm_vals(e)]
    if isinstance(v, float) and v.is_integer():
        return [str(int(v))]
    return [str(v)]

def grounded_in(values, text):
    return all(v.lower() in text for v in values)

# ---- self-test of the grounding function (guards against the v1 always-true defect) ----
assert grounded_in(["alice@x.com"], "send to alice@x.com please") is True
assert grounded_in(["evil@y.com"], "send to alice@x.com please") is False
assert grounded_in([], "anything") is True
assert norm_vals(100.0) == ["100"] and norm_vals(["a", ["b"]]) == ["a", "b"]

def two_pass(cfg, action, ctx):
    res = 'Resource::"doc"' if action == "read" else 'Sink::"sink"'
    def ev(approved):
        c = copy.deepcopy(ctx); c["approved"] = approved
        return is_authorized({"principal": 'Agent::"procurement"', "action": f'Action::"{action}"', "resource": res, "context": c},
                             cfg["P"], [], schema=cfg["S"])
    r1 = ev(True)
    if r1.diagnostics.errors or r1.decision != Decision.Allow:
        return "DENY"
    r2 = ev(False)
    if r2.diagnostics.errors:
        return "DENY"
    return "PERMIT" if r2.decision == Decision.Allow else "APPROVAL_REQUIRED"

class Session:
    def __init__(self, prompt, cfg):
        self.conf, self.integ, self.cfg = 0, 2, cfg
        self.prompt = prompt.lower(); self.trusted_text = self.prompt
        self.thr = cfg["ANN"]["untrusted_threshold"]

    def decide(self, ann, fn, args):
        a = ann[fn]
        params = {"all_grounded": True}
        if self.cfg["v2ctx"]:
            params["prompt_grounded"] = True
        if a["kind"] == "read":
            ctx = {"session": {"conf": self.conf, "integ": self.integ},
                   "target": {"external": False, "clearance": 3, "untrusted_threshold": self.thr}, "params": params}
            return two_pass(self.cfg, "read", ctx), None
        cons = [x for k in a["consequential"] for x in norm_vals(args.get(k))]
        g = grounded_in(cons, self.trusted_text)
        params["all_grounded"] = g
        if self.cfg["v2ctx"]:
            params["prompt_grounded"] = grounded_in(cons, self.prompt)
        ctx = {"session": {"conf": self.conf, "integ": self.integ},
               "target": {"external": a["external"], "clearance": a["clearance"], "untrusted_threshold": self.thr}, "params": params}
        return two_pass(self.cfg, "send", ctx), {"grounded": g, "prompt_grounded": params.get("prompt_grounded")}

    def observe(self, ann, fn, output):
        a = ann[fn]
        if a["kind"] not in ("read", "fetch"):
            return
        self.conf = max(self.conf, a["conf"])
        if a["integ_source"] == "untrusted":
            self.integ = 0
        else:
            self.trusted_text += " " + str(output).lower()

def execute(suite, env, calls, mode, prompt, cfg):
    rt = FunctionsRuntime(suite.tools); ann = cfg["ANN"]["suites"][suite.name]
    sess = Session(prompt, cfg); recs = []
    for c in calls:
        fn, args = c.function, dict(c.args)
        if mode in ("native", "permit_all"):
            dec, g = "PERMIT", None
        elif mode == "deny_all":
            dec, g = ("PERMIT" if ann[fn]["kind"] == "read" else "DENY"), None
        else:
            dec, g = sess.decide(ann, fn, args)
        if dec == "PERMIT":
            out, err = rt.run_function(env, fn, args, raise_on_error=False)
            sess.observe(ann, fn, out)
        recs.append({"fn": fn, "decision": dec, "g": g, "_call": c if dec == "PERMIT" else None})
    return recs

def gto(t):
    return getattr(t, "GROUND_TRUTH_OUTPUT", "") or ""

def trace(recs):
    return [r["_call"] for r in recs if r["_call"] is not None]

def utility(task, pre, post, recs):
    u = task.utility_from_traces(gto(task), pre, post, trace(recs))
    return bool(u if u is not None else task.utility(gto(task), pre, post))

def security(task, out, pre, post, recs):
    s = task.security_from_traces(out, pre, post, trace(recs))
    return bool(s if s is not None else task.security(out, pre, post))

def slim(recs):
    return [{"fn": r["fn"], "decision": r["decision"], "g": r["g"]} for r in recs]

MODES = ["native", "permit_all", "deny_all"] + [f"mandate:{k}" for k in CONFIGS]
rows, t0 = [], time.time()
for sname in ["workspace", "travel", "banking", "slack"]:
    suite = get_suite(VERSION, sname)
    base_env = suite.load_and_inject_default_environment(suite.get_injection_vector_defaults())
    for uid, ut in suite.user_tasks.items():
        pre = copy.deepcopy(base_env); calls = ut.ground_truth(copy.deepcopy(pre)); row = {"suite": sname, "kind": "benign", "user_task": uid}
        for mode in MODES:
            cfg = LOADED[mode.split(":")[1]] if mode.startswith("mandate") else LOADED["baseline"]
            post = copy.deepcopy(pre); recs = execute(suite, post, calls, mode.split(":")[0], ut.PROMPT, cfg)
            row[mode] = {"utility": utility(ut, pre, post, recs), "calls": slim(recs)}
        rows.append(row)
    for iid, it in suite.injection_tasks.items():
        for uid, ut in suite.user_tasks.items():
            pre = copy.deepcopy(base_env); cu = ut.ground_truth(copy.deepcopy(pre)); ci = it.ground_truth(copy.deepcopy(pre))
            row = {"suite": sname, "kind": "attack", "user_task": uid, "injection_task": iid, "n_user_calls": len(cu)}
            for mode in ["native", "permit_all"] + [f"mandate:{k}" for k in CONFIGS]:
                cfg = LOADED[mode.split(":")[1]] if mode.startswith("mandate") else LOADED["baseline"]
                post = copy.deepcopy(pre); recs = execute(suite, post, cu + ci, mode.split(":")[0], ut.PROMPT, cfg)
                row[mode] = {"attack_succeeded": security(it, gto(ut), pre, post, recs),
                             "injection_calls": slim(recs[len(cu):]), "user_decisions": [r["decision"] for r in recs[:len(cu)]]}
            rows.append(row)
    print(sname, "done", round(time.time() - t0, 1), "s", flush=True)

ben = [r for r in rows if r["kind"] == "benign"]; att = [r for r in rows if r["kind"] == "attack"]
nat_ben = [r for r in ben if r["native"]["utility"]]; nat_att = [r for r in att if r["native"]["attack_succeeded"]]
key = lambda r: r["suite"] + "/" + r["user_task"] + ("+" + r["injection_task"] if r["kind"] == "attack" else "")
summary = {"LABEL": "in-process decision emulation (S4a v2). Not mediation, not LLM behaviour, not attack success rates.",
           "benchmark": VERSION, "benign_tasks": len(ben), "benign_native_pass": len(nat_ben), "attack_pairs": len(att),
           "attack_native_success": len(nat_att),
           "parity_benign_mismatches": [key(r) for r in nat_ben if not r["permit_all"]["utility"]],
           "parity_attack_mismatches": [key(r) for r in att if r["native"]["attack_succeeded"] != r["permit_all"]["attack_succeeded"]],
           "negative_control_deny_all_changes_outcome": sum(1 for r in nat_ben if not r["deny_all"]["utility"]),
           "configs": {}}
for k in CONFIGS:
    m = f"mandate:{k}"
    dec_b = [c["decision"] for r in ben for c in r[m]["calls"]]
    tasks_needing_approval = [key(r) for r in ben if any(c["decision"] == "APPROVAL_REQUIRED" for c in r[m]["calls"])]
    canon = json.dumps([{"k": key(r), "d": [c["decision"] for c in (r[m]["calls"] if r["kind"] == "benign" else r[m]["injection_calls"])],
                         "o": r[m].get("utility", r[m].get("attack_succeeded"))} for r in rows], sort_keys=True)
    summary["configs"][k] = {
        "inputs_sha256": LOADED[k]["sha256"],
        "benign_utility_preserved_without_approvals": sum(1 for r in nat_ben if r[m]["utility"]),
        "benign_tasks_needing_any_approval": len(tasks_needing_approval),
        "benign_call_decisions": {d: dec_b.count(d) for d in sorted(set(dec_b))},
        "attacks_prevented": sum(1 for r in nat_att if not r[m]["attack_succeeded"]),
        "attacks_still_succeeding": [key(r) for r in nat_att if r[m]["attack_succeeded"]],
        "decision_hash": hashlib.sha256(canon.encode()).hexdigest()}
b, c = "mandate:baseline", "mandate:candidate"
summary["comparison"] = {
    "benign_regressions_candidate_loses_utility": [key(r) for r in nat_ben if r[b]["utility"] and not r[c]["utility"]],
    "benign_improvements": [key(r) for r in nat_ben if not r[b]["utility"] and r[c]["utility"]],
    "attack_regressions_candidate_allows_baseline_blocked": [key(r) for r in nat_att if not r[b]["attack_succeeded"] and r[c]["attack_succeeded"]],
    "attacks_newly_prevented_by_candidate": len([r for r in nat_att if r[b]["attack_succeeded"] and not r[c]["attack_succeeded"]])}
summary["seconds"] = round(time.time() - t0, 1)
(OUT / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1)[:6000])
