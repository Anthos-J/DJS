"""S2 spike harness: cedarpy two-pass evaluation vs independent oracle (bounded exhaustive),
schema validation, and error behaviour. Spike code only."""
import itertools, json, sys, time, hashlib, platform
from pathlib import Path
import cedarpy
from cedarpy import is_authorized, validate_policies, Decision, PolicySet, Schema

CFG = Path(__file__).resolve().parent.parent / "config"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
schema_txt = (CFG / "schema.cedarschema").read_text()
P_txt = (CFG / "policies_P.cedar").read_text()
results = []
def rec(tid, expected, observed, verdict, **kw):
    r = {"id": tid, "expected": expected, "observed": observed, "verdict": verdict, **kw}
    results.append(r); print(json.dumps(r)[:400])

# ---------- T1 schema validation ----------
v = validate_policies(P_txt, schema_txt)
rec("S2-T1a", "P validates", {"passed": v.validation_passed, "errors": [str(e) for e in v.errors]},
    "PASS" if v.validation_passed else "FAIL")
bad = 'permit(principal, action == Action::"send", resource) when { context.nonexistent_attr == 1 };'
v2 = validate_policies(bad, schema_txt)
rec("S2-T1b", "undeclared attribute rejected (negative control)",
    {"passed": v2.validation_passed, "errors": [str(e)[:200] for e in v2.errors]},
    "PASS" if not v2.validation_passed and v2.errors else "FAIL")

# ---------- T2 bounded exhaustive two-pass vs oracle ----------
pset = PolicySet.from_str(P_txt) if hasattr(PolicySet, "from_str") else P_txt
sch = Schema.from_str(schema_txt) if hasattr(Schema, "from_str") else schema_txt
entities = []

def two_pass(principal, action, resource, ctx):
    errs = []
    def ev(approved):
        c = json.loads(json.dumps(ctx)); c["approved"] = approved
        r = is_authorized({"principal": principal, "action": action, "resource": resource, "context": c},
                          pset, entities, schema=sch)
        errs.extend(r.diagnostics.errors)
        return r
    r1 = ev(True)
    if r1.diagnostics.errors: return "DENY", errs
    if r1.decision != Decision.Allow: return "DENY", errs
    r2 = ev(False)
    if r2.diagnostics.errors: return "DENY", errs
    return ("APPROVAL_REQUIRED" if r2.decision != Decision.Allow else "PERMIT"), errs

def oracle(pr, act, res, conf, integ, ext, clr, thr, grounded):
    # written independently from v3 §4 prose
    if res == "hr_records": return "DENY"
    if pr != "procurement": return "DENY"
    if act == "read": return "PERMIT"
    needs = (ext and conf > clr) or (ext and integ == 0 and conf >= thr) or (not grounded)
    return "APPROVAL_REQUIRED" if needs else "PERMIT"

combos = itertools.product(["procurement", "intruder"],
                           [("read", "Resource", "doc"), ("read", "Resource", "hr_records"), ("send", "Sink", "ext_email")],
                           range(4), range(3), [True, False], range(4), range(4), [True, False])
n = mism = 0; mismatches = []; t0 = time.perf_counter(); evals = 0
for pr, (act, rtype, rid), conf, integ, ext, clr, thr, gr in combos:
    ctx = {"session": {"conf": conf, "integ": integ},
           "target": {"external": ext, "clearance": clr, "untrusted_threshold": thr},
           "params": {"all_grounded": gr}, "approved": False}
    got, errs = two_pass(f'Agent::"{pr}"', f'Action::"{act}"', f'{rtype}::"{rid}"', ctx)
    exp = oracle(pr, act, rid, conf, integ, ext, clr, thr, gr)
    n += 1; evals += 2
    if got != exp or errs:
        mism += 1
        if len(mismatches) < 20: mismatches.append({"in": [pr, act, rid, conf, integ, ext, clr, thr, gr], "got": got, "exp": exp, "errs": errs})
dt = time.perf_counter() - t0
rec("S2-T2", "100% agreement with oracle, no errors", {"cases": n, "mismatches": mism, "examples": mismatches},
    "PASS" if mism == 0 else "FAIL", seconds=round(dt, 3), approx_evals_per_sec=round(evals / dt))

# ---------- T3 error behaviour ----------
ctx_missing = {"session": {"conf": 0, "integ": 2},
               "target": {"external": True, "clearance": 3, "untrusted_threshold": 3},
               "params": {"all_grounded": True}}          # 'approved' missing
req = {"principal": 'Agent::"procurement"', "action": 'Action::"send"', "resource": 'Sink::"ext_email"', "context": ctx_missing}
r_noschema = is_authorized(req, P_txt, [])
rec("S2-T3a", "record decision+errors without schema; PEP maps errors->DENY",
    {"decision": r_noschema.decision.value, "reasons": list(r_noschema.diagnostics.reasons),
     "errors": [e[:300] for e in r_noschema.diagnostics.errors]},
    "RECORDED",
    note="Short-circuit && never evaluated the missing attribute -> no error, Allow. Shows missing attributes can go unnoticed without a schema.")
# T3c: force evaluation of the missing attribute (conf > clearance so g3a reaches !context.approved)
ctx_force = {"session": {"conf": 3, "integ": 2},
             "target": {"external": True, "clearance": 0, "untrusted_threshold": 3},
             "params": {"all_grounded": True}}                # 'approved' missing
req_force = {"principal": 'Agent::"procurement"', "action": 'Action::"send"', "resource": 'Sink::"ext_email"', "context": ctx_force}
r_force = is_authorized(req_force, P_txt, [])
rec("S2-T3c", "no schema, missing attr forced: forbid errors -> skipped -> Allow WITH errors (proves deny-on-error rule needed)",
    {"decision": r_force.decision.value, "reasons": list(r_force.diagnostics.reasons),
     "errors": [e[:300] for e in r_force.diagnostics.errors]},
    "PASS" if r_force.diagnostics.errors else "FAIL",
    note="PASS = errors observable. Decision value recorded; Allow here would confirm skip-on-error danger.")
r_schema = is_authorized(req, P_txt, [], schema=schema_txt)
rec("S2-T3b", "with schema: request validation error -> Deny + errors",
    {"decision": r_schema.decision.value, "errors": [e[:300] for e in r_schema.diagnostics.errors]},
    "PASS" if r_schema.diagnostics.errors and r_schema.decision != Decision.Allow else "FAIL")

# ---------- T6 throughput (single requests, pre-parsed handles) ----------
ctx = {"session": {"conf": 1, "integ": 2}, "target": {"external": True, "clearance": 1, "untrusted_threshold": 3},
       "params": {"all_grounded": True}, "approved": False}
t0 = time.perf_counter(); N = 3000
for _ in range(N):
    is_authorized({"principal": 'Agent::"procurement"', "action": 'Action::"send"', "resource": 'Sink::"x"', "context": ctx}, pset, entities, schema=sch)
dt = time.perf_counter() - t0
rec("S2-T6", "record throughput", {"requests": N, "seconds": round(dt, 3), "per_sec": round(N / dt)}, "RECORDED")

manifest = {"python": platform.python_version(), "cedarpy": getattr(cedarpy, "__version__", "see pip freeze"),
            "policies_sha256": hashlib.sha256(P_txt.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(schema_txt.encode()).hexdigest()}
(OUT / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print("SUMMARY", {r["id"]: r["verdict"] for r in results})
