"""S2-T4 in the container: SymCC implication checks with fail-closed verdict parsing, plus parser tests.
Usage: python s2_symcc.py <out_dir>. Needs `cedar` (experimental CLI 4.13.0) on PATH and CVC5 set."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from symcc_verdict import parse, gate  # noqa: E402

CFG = Path(__file__).resolve().parent.parent / "config"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
results, log = [], []

def rec(tid, expected, observed, verdict, **kw):
    r = {"id": tid, "expected": expected, "observed": observed, "verdict": verdict, **kw}
    results.append(r); print(json.dumps(r)[:500], flush=True)

def symcc(p1, ptype, action, rtype, env=None):
    cmd = ["cedar", "symcc", "--principal-type", ptype, "--action", action, "--resource-type", rtype,
           "-s", str(CFG / "schema.cedarschema"), "--counterexample", "implies",
           "--policies1", str(CFG / p1), "--policies2", str(CFG / "Q_G3a.cedar")]
    cp = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=300)
    text = cp.stdout + cp.stderr
    log.append({"cmd": cmd, "env": env or {}, "rc": cp.returncode, "output": text})
    return cp.returncode, text

envs = [("Agent", 'Action::"send"', "Sink"), ("Agent", 'Action::"read"', "Resource")]
for p1, want in [("policies_P.cedar", "HOLDS"), ("policies_P_bad.cedar", None)]:
    for pt, act, rt in envs:
        rc, text = symcc(p1, pt, act, rt)
        v = parse(rc, text)
        # P must hold in every environment. P_bad removes `!context.approved` from the send rule, so it
        # must fail for (send, Sink); for (read, Resource) the seeded bug is irrelevant and it must hold.
        exp = want or ("DOES_NOT_HOLD" if act.endswith('"send"') else "HOLDS")
        rec(f"S2-T4-{p1.split('.')[0]}-{act.split('::')[1].strip(chr(34))}", f"verdict {exp}",
            {"rc": rc, "verdict": v, "first_line": text.strip().splitlines()[0] if text.strip() else ""},
            "PASS" if v == exp else "FAIL")

# AM10 reproduction: exit code alone cannot distinguish HOLDS from DOES_NOT_HOLD
rcs = {(e["cmd"][-3].rsplit("/", 1)[-1], e["cmd"][5]): e["rc"] for e in log}  # (policy file, action)
rec("S2-T4-exitcode", "record CLI exit codes (AM10: exit 0 even when property fails)", {str(k): v for k, v in rcs.items()},
    "RECORDED", am10_reproduced=all(v == 0 for v in rcs.values()))

# Real failure modes must parse as UNKNOWN (fail closed)
rc, text = symcc("policies_P.cedar", *envs[0], env={"CVC5": "/nonexistent/cvc5"})
rec("S2-T4-neg-missing-solver", "UNKNOWN, gate false", {"rc": rc, "verdict": parse(rc, text), "head": text[:300]},
    "PASS" if parse(rc, text) == "UNKNOWN" and not gate(rc, text) else "FAIL")
rc, text = symcc("does_not_exist.cedar", *envs[0])
rec("S2-T4-neg-missing-policy", "UNKNOWN, gate false", {"rc": rc, "verdict": parse(rc, text), "head": text[:300]},
    "PASS" if parse(rc, text) == "UNKNOWN" and not gate(rc, text) else "FAIL")

# Synthetic parser cases
good = "✓ Policy set 1 implies policy set 2: VERIFIED\n"
bad = "✗ Policy set 1 implies policy set 2: DOES NOT HOLD\n  Counterexample found:\nprincipal: ...\n"
synth = [
    ("verified", 0, good, "HOLDS"),
    ("does-not-hold", 0, bad, "DOES_NOT_HOLD"),
    ("verified-but-nonzero-exit", 1, good, "UNKNOWN"),
    ("both-lines", 0, good + bad, "UNKNOWN"),
    ("two-verified-lines", 0, good + good, "UNKNOWN"),
    ("empty", 0, "", "UNKNOWN"),
    ("word-VERIFIED-elsewhere", 0, "note: not VERIFIED yet\n", "UNKNOWN"),
    ("verdict-with-suffix", 0, "✓ Policy set 1 implies policy set 2: VERIFIED (partially)\n", "UNKNOWN"),
    ("does-not-hold-no-counterexample", 0, "✗ Policy set 1 implies policy set 2: DOES NOT HOLD\n", "UNKNOWN"),
    ("error-text", 2, "Error: failed to run cvc5\n", "UNKNOWN"),
]
obs = {n: {"got": parse(rc, t), "want": w, "gate": gate(rc, t)} for n, rc, t, w in synth}
rec("S2-T4-parser", "every synthetic case parsed as expected; gate true only for a clean VERIFIED",
    obs, "PASS" if all(o["got"] == o["want"] and o["gate"] == (o["want"] == "HOLDS") for o in obs.values()) else "FAIL")

(OUT / "symcc_log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
(OUT / "results.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
print("SUMMARY", {r["id"]: r["verdict"] for r in results})
