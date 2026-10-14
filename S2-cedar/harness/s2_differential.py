"""S2-T5: differential test cedarpy (engine 4.12.x) vs cedar CLI 4.13.0 on single-pass decisions.
Spike code only. Usage: python s2_differential.py <cedar.exe> <out_dir> [n_samples]"""
import itertools, json, random, subprocess, sys, tempfile, os
from pathlib import Path
from cedarpy import is_authorized, Decision

CEDAR, OUT = sys.argv[1], Path(sys.argv[2]); N = int(sys.argv[3]) if len(sys.argv) > 3 else 300
OUT.mkdir(parents=True, exist_ok=True)
CFG = Path(__file__).resolve().parent.parent / "config"
schema = (CFG / "schema.cedarschema").read_text(); P = (CFG / "policies_P.cedar").read_text()
entities_file = OUT / "entities.json"; entities_file.write_text("[]")

space = list(itertools.product(["procurement", "intruder"],
                               [("read", "Resource", "doc"), ("read", "Resource", "hr_records"), ("send", "Sink", "ext_email")],
                               range(4), range(3), [True, False], range(4), range(4), [True, False], [True, False]))
random.seed(20261015); sample = random.sample(space, N)
rows = []; mism = 0
for pr, (act, rt, rid), conf, integ, ext, clr, thr, gr, appr in sample:
    ctx = {"session": {"conf": conf, "integ": integ}, "target": {"external": ext, "clearance": clr, "untrusted_threshold": thr},
           "params": {"all_grounded": gr}, "approved": appr}
    py = is_authorized({"principal": f'Agent::"{pr}"', "action": f'Action::"{act}"', "resource": f'{rt}::"{rid}"', "context": ctx},
                       P, [], schema=schema)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(ctx, f); cpath = f.name
    cp = subprocess.run([CEDAR, "authorize", "-l", f'Agent::"{pr}"', "-a", f'Action::"{act}"', "-r", f'{rt}::"{rid}"',
                         "-c", cpath, "-p", str(CFG / "policies_P.cedar"), "-s", str(CFG / "schema.cedarschema"),
                         "--entities", str(entities_file)], capture_output=True, text=True)
    os.unlink(cpath)
    out = (cp.stdout + cp.stderr).strip()
    cli = "Allow" if out.startswith("ALLOW") else ("Deny" if out.startswith("DENY") else f"OTHER:{out[:120]}")
    same = (cli == py.decision.value)
    mism += (not same)
    rows.append({"in": [pr, act, rid, conf, integ, ext, clr, thr, gr, appr], "cedarpy": py.decision.value, "cli": cli, "same": same})
(OUT / "differential.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
res = {"id": "S2-T5", "expected": "identical decisions", "observed": {"samples": N, "mismatches": mism,
       "first_mismatches": [r for r in rows if not r["same"]][:5]}, "verdict": "PASS" if mism == 0 else "FAIL"}
(OUT / "results.jsonl").write_text(json.dumps(res) + "\n"); print(json.dumps(res)[:800])
