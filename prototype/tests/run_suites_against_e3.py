"""Regression: run the E1 and E2 test suites with the engine class replaced by E3 (engine_e3.Engine).
Usage: python tests/run_suites_against_e3.py. Prints per-test results; differences are expected only where E3 is
intentionally stricter, and each such difference must be explained in the E3 report."""
import importlib, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import mandate.engine as e2mod
import mandate.engine_e3 as e3mod

e2mod.Engine = e3mod.Engine          # the suites import Engine from mandate.engine
e2mod.HAVE_CEDAR = e3mod.HAVE_CEDAR
res = {}
for name in ("test_engine", "test_engine_e2"):
    mod = importlib.import_module(name)
    mod.Engine = e3mod.Engine
    if hasattr(mod, "engmod"):
        mod.engmod = e3mod           # fail-closed test toggles HAVE_CEDAR on the engine module
    suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
    def flat(s):
        for x in s:
            if isinstance(x, unittest.TestSuite):
                yield from flat(x)
            else:
                yield x
    ids = [str(c).split(" ")[0] for c in flat(suite)]
    r = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w")).run(suite)
    bad = {str(t).split(" ")[0]: (tb.splitlines()[-1][:200]) for t, tb in r.failures + r.errors}
    for tid in ids:
        res[f"{name}.{tid}"] = "PASS" if tid not in bad else "FAIL: " + bad[tid]
for k, v in res.items():
    print(f"{v[:4]:5s} {k}  {v[5:] if v != 'PASS' else ''}")
print("SUMMARY", sum(v == "PASS" for v in res.values()), "/", len(res))
