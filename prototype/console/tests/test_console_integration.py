"""Console + live-stack integration tests (run against a stack started by demo/launch.sh).
Every state-changing check goes through the console exactly as the UI does (same endpoints, same headers) and
verifies the result from the real backend (control-plane API, tool-server effects inside scenario transcripts).
Usage: python console/tests/test_console_integration.py      -> writes console/tests/runs/<ts>/results.json
The run takes ~10 minutes: it executes all 12 live journeys, recovery, and a full reset."""
import json, os, subprocess, sys, time, unittest, urllib.error, urllib.request
from pathlib import Path

C = os.environ.get("MANDATE_CONSOLE", "http://127.0.0.1:8090")
CTRL = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parents[2]


def call(path, body=None, base=C, headers=None, method=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method or ("GET" if body is None else "POST"), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            raw = r.read(); ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(raw) if "json" in ct else raw.decode(errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def action(path, body=None):
    return call(path, body or {}, headers={"X-Console-Action": "1"})


def scenario(sid):
    st, r = action(f"/console/scenarios/{sid}/run")
    assert st == 200, (st, r)
    return r


def dc(*a):
    env = {**os.environ, "MSYS_NO_PATHCONV": "1", "SPIKE_IMAGE": "mandate-spike-py312:wave2", "NGINX_IMAGE": "x", "RUN_DIR": "x"}
    return subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), *a], capture_output=True, text=True, env=env, timeout=180)


class T01Surface(unittest.TestCase):
    def test_ui_served(self):
        st, body = call("/")
        self.assertEqual(st, 200); self.assertIn("MANDATE", body)
        for f in ("/app.js", "/styles.css", "/limitations.json"):
            self.assertEqual(call(f)[0], 200, f)

    def test_path_traversal_blocked(self):
        self.assertEqual(call("/../console.py")[0], 404); self.assertEqual(call("/%2e%2e/console.py")[0], 404)

    def test_health_reports_real_engine(self):
        st, h = call("/console/health")
        self.assertEqual(st, 200); self.assertTrue(h["control"]["reachable"]); self.assertEqual(h["control"]["meta"]["engine"], "E4.2.1")
        self.assertTrue(h["engine_ok"]); self.assertEqual(h["container_env"].get("MANDATE_ENGINE"), "E4.2.1")

    def test_console_actions_need_csrf_header(self):
        self.assertEqual(call("/console/reset", {})[0], 403)

    def test_unknown_scenario(self):
        self.assertEqual(action("/console/scenarios/nope/run")[0], 404)

    def test_results_from_recorded_evidence(self):
        st, r = call("/console/results")
        self.assertEqual(st, 200)
        fin = next(c for c in r["comparison"] if c["engine"].startswith("E4.2.1"))
        self.assertEqual(fin["attack_scenarios"], 1260); self.assertEqual(fin["attack_outcomes"].get("SUCCEEDED"), 30)
        self.assertEqual(fin["benign_outcomes"].get("APPROVAL_FRICTION"), 127); self.assertTrue(r["final_repeat_hash_equal"])
        self.assertIn("C4 below-budget cumulative reading of unrelated items", r["families"])
        self.assertTrue(any(l["id"].startswith("L1") for l in r["limitations"]["items"]))

    def test_diagnostics(self):
        st, d = call("/console/diagnostics")
        self.assertEqual(st, 200); self.assertIsNotNone(d["last_deploy"]); self.assertIn("evidence_verify", d)


class T02AuthAndValidation(unittest.TestCase):
    def test_control_plane_requires_owner_token(self):
        self.assertEqual(call("/api/agents", base=CTRL)[0], 401)
        self.assertEqual(call("/api/agents", base=CTRL, headers={"X-Owner-Token": "wrong"})[0], 401)

    def test_status_change_requires_reason(self):
        st, j = call("/api/agents/agent:cell-b/status", {"status": "quarantined"})
        self.assertEqual(st, 400)

    def test_hr_task_without_scope_refused_by_server(self):
        call("/api/agents/agent:cell-b/task", {"role": "hr_assistant"})
        try:
            st, j = call("/api/agents/agent:cell-b/task", {"task": "records", "instruction": "maintain hr records for grace"})
            self.assertEqual(st, 400); self.assertIn("declared subject", j["error"])
            st, j = call("/api/agents/agent:cell-b/task", {"task": "records", "instruction": "x", "subjects": ["grace,dave"]})
            self.assertEqual(st, 400)
            st, j = call("/api/agents/agent:cell-b/task", {"task": "records", "instruction": "x", "subjects": ["grace"]})
            self.assertEqual(st, 200); self.assertEqual(j["subjects"], ["grace"])
            st, j = call("/api/agents", {"agent_id": "probe-hr", "role": "hr_assistant", "task": "records"})
            self.assertEqual(st, 400)
        finally:
            call("/api/agents/agent:cell-b/task", {"role": "research"}); call("/api/agents/agent:cell-b/task", {"task": "research", "instruction": "research valves"})

    def test_resolving_unknown_or_resolved_approval_fails(self):
        self.assertEqual(call("/api/approvals/apr-doesnotexist", {"approve": True})[0], 400)


class T03Journeys(unittest.TestCase):
    """The 12 judge journeys, in runbook order, through the real PEP/tool-server path."""
    def _ok(self, sid):
        r = scenario(sid)
        self.assertEqual(r["verdict"], "PASS", json.dumps([c for c in r["checks"] if not c["ok"]], default=str)[:800])
        return r

    def test_s01_to_s09(self):
        for i in range(1, 10):
            with self.subTest(scenario=i):
                self._ok(f"s{i}")

    def test_s05_approval_executes_exactly_once(self):
        r = self._ok("s5")
        self.assertTrue(any("exactly one purchase" in c["what"] and c["ok"] for c in r["checks"]))

    def test_s10_persistence(self):
        self._ok("s10")
        call("/api/agents/agent:cell-b/status", {"status": "active", "reason": "test cleanup"})

    def test_s12_control_down_and_service_unavailable(self):
        self._ok("s12")


class T04Unavailable(unittest.TestCase):
    def test_proxy_reports_503_when_control_down(self):
        dc("stop", "control")
        try:
            st, j = call("/api/agents"); self.assertEqual(st, 503); self.assertIn("unreachable", j["error"])
            st, h = call("/console/health"); time.sleep(3.5); st, h = call("/console/health")
            self.assertFalse(h["control"]["reachable"])
        finally:
            dc("start", "control")
            for _ in range(60):
                if call("/api/meta")[0] == 200:
                    break
                time.sleep(1)


class T05AuditLossAndRecovery(unittest.TestCase):
    def test_s11_then_recovery_then_ack(self):
        r = scenario("s11"); self.assertEqual(r["verdict"], "PASS", r["checks"])
        self.assertEqual(call("/api/meta")[0], 503)
        st, rec = action("/console/recovery/start"); self.assertEqual(st, 200); self.assertTrue(rec["ok"], rec)
        st, m = call("/api/meta"); self.assertTrue(m["recovery"]); self.assertIn("history", m["recovery_reason"])
        o = scenario("s1")                                         # in recovery every read needs approval
        self.assertEqual(o["verdict"], "FAIL")
        self.assertTrue(any(p.get("ok") is False and "APPROVAL_REQUIRED" in p.get("text", "") for s in o["steps"] for p in (s.get("pep_results") or [])))
        st, j = call("/api/recovery/ack", {"note": "integration test"}); self.assertEqual(st, 200); self.assertFalse(j["recovery"])
        self.assertEqual(scenario("s1")["verdict"], "PASS")


class T07NewFeatures(unittest.TestCase):
    """UI-P2: what-if simulator, evidence pack, attack graph data."""
    def _counts(self):
        m = call("/api/meta")[1]; return (m["counts"]["decisions"], m["counts"]["pending_approvals"], m["counts"]["quarantined"], m["audit"]["records"])

    def test_simulator_is_a_true_dry_run(self):
        before = self._counts()
        st, r = call("/api/simulate", {"agent_id": "agent:cell-b", "tool": "send_email", "args": {"to": "x@collect.example"}, "destination": "collect.example"})
        self.assertEqual(st, 200); self.assertEqual(r["decision"]["response"], "DENY"); self.assertFalse(r["executed"]); self.assertTrue(r["live_state_unchanged"])
        st, r = call("/api/simulate", {"agent_id": "agent:cell-b", "tool": "read_doc", "args": {"page": "valves"}})
        self.assertEqual(r["decision"]["response"], "ALLOW")
        self.assertEqual(self._counts(), before)                       # nothing recorded, held or quarantined
        self.assertEqual(call("/api/simulate", {})[0], 400)
        self.assertEqual(call("/api/simulate", {"agent_id": "a", "tool": "t"}, base=CTRL)[0], 401)

    def test_evidence_pack_verifies_and_detects_tampering(self):
        sys.path.insert(0, str(ROOT / "console")); import verify_evidence_pack as v
        scenario("s2")
        ev = call("/api/events?agent=agent:cell-a")[1]
        did = next(e["decision_id"] for e in reversed(ev) if e["tool"] == "read_hr_record" and e["response"] == "DENY")
        st, p = call(f"/console/evidence/{did}"); self.assertEqual(st, 200)
        self.assertTrue(all(c["ok"] for c in p["_self_check"]))
        pack = json.loads((ROOT / p["_saved_as"]).read_text(encoding="utf-8"))
        self.assertTrue(all(g for _, g, _ in v.verify(pack))); self.assertEqual(pack["tool_server_effects"], [])
        pack["audit"]["records"][-1]["entry"]["response"] = "ALLOW"; pack["decision"]["response"] = "ALLOW"
        self.assertFalse(all(g for _, g, _ in v.verify(pack)))
        self.assertEqual(call("/console/evidence/dec-nope")[0], 404)
        call("/api/agents/agent:cell-a/status", {"status": "active", "reason": "test cleanup"})

    def test_ui_pages_served(self):
        body = call("/")[1]
        for r in ("#/simulate", "#/graph", "#/llm"):
            self.assertIn(r, body)
        js = call("/app.js")[1]
        for v in ("VIEWS.simulate", "VIEWS.graph", "Export verifiable evidence pack"):
            self.assertIn(v, js)


class T06Reset(unittest.TestCase):
    def test_reset_returns_to_baseline(self):
        st, r = action("/console/reset"); self.assertEqual(st, 200); self.assertTrue(r["ok"], r)
        st, ags = call("/api/agents"); self.assertEqual({a["agent_id"] for a in ags}, {"agent:cell-a", "agent:cell-b"})
        self.assertTrue(all(a["status"] == "active" for a in ags))
        st, m = call("/api/meta"); self.assertFalse(m["recovery"]); self.assertEqual(m["engine"], "E4.2.1"); self.assertEqual(m["counts"]["pending_approvals"], 0)


if __name__ == "__main__":
    t0 = time.time()
    res = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    out = ROOT / "console" / "tests" / "runs" / time.strftime("%Y%m%dT%H%M%S"); out.mkdir(parents=True, exist_ok=True)
    total = res.testsRun; bad = len(res.failures) + len(res.errors)
    (out / "results.json").write_text(json.dumps({"total": total, "passed": total - bad, "failures": [str(t) for t, _ in res.failures], "errors": [str(t) for t, _ in res.errors],
                                                  "details": [tb[-1500:] for _, tb in res.failures + res.errors], "started": t0, "finished": time.time()}, indent=1))
    print("RESULTS", out / "results.json"); sys.exit(0 if res.wasSuccessful() else 1)
