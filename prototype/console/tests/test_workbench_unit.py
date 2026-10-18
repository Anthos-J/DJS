"""Workbench unit tests (no Docker): request validation, document store, argument sanitisation, AI-mode failure handling,
and that the workbench only ever acts through agent_call (the real path) and the control-plane API.
Usage: python -m unittest console/tests/test_workbench_unit.py   (from validation/prototype)"""
import json, os, shutil, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import workbench as W   # noqa: E402

ROLES = Path(__file__).resolve().parent.parent.parent / "config" / "roles_e431.json"


class FakeStack:
    """Stands in for the console helpers. Records every agent_call so tests can prove nothing bypasses it."""
    def __init__(self):
        self.calls, self.eff, self.events, self.n = [], [], [], 0
        self.lock = threading.Lock()

    def control(self, path, body=None, timeout=8):
        if path.startswith("/api/agents/") and path.endswith("/task"):
            return 200, {"ok": True}
        if path.startswith("/api/agents/") and path.endswith("/status"):
            return 200, {"status": body.get("status")}
        if path.startswith("/api/events"):
            return 200, self.events[-6:]
        if path.startswith("/api/audit"):
            return 200, {"records": []}
        if path in ("/api/approvals", "/api/alerts"):
            return 200, []
        if path == "/api/agents":
            return 200, [{"agent_id": "agent:cell-b", "status": "active"}, {"agent_id": "agent:cell-a", "status": "active"}]
        return 200, {}

    def agent_call(self, cell, steps):
        tool, args = steps[0]; self.calls.append((cell, tool, args)); self.n += 1
        resp = "DENY" if tool == "read_hr_record" else "ALLOW"
        self.events.append({"decision_id": f"dec-{self.n}", "tool": tool, "response": resp, "reason": "test", "ts": time.time()})
        if resp == "ALLOW":
            self.eff.append({"tool": tool, "decision_id": f"dec-{self.n}"})
        return {"results": [{"ok": resp == "ALLOW", "text": "ok" if resp == "ALLOW" else "DENY: test"}]}

    def effects(self):
        return list(self.eff)

    def H(self):
        return {"control": self.control, "agent_call": self.agent_call, "effects": self.effects, "lock": self.lock, "seed": {}}


class FakeLLM:
    MODEL = "fake-model"
    def __init__(self, turns=None, exc=None, enabled=True):
        self.turns, self.exc, self._en = list(turns or []), exc, enabled
    def enabled(self):
        return self._en
    def chat(self, messages, tools):
        if self.exc:
            raise self.exc
        return self.turns.pop(0) if self.turns else {"content": "done", "tool_calls": []}


def wait(rid):
    for _ in range(200):
        r = W.get_run(rid)
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.02)
    return r


BASE = {"profile": "research", "task": "document_review", "instruction": "Summarise the documents."}


class TestValidation(unittest.TestCase):
    def v(self, **kw):
        return W._validate({**BASE, **kw}, ROLES, True)

    def test_good_requests(self):
        self.assertIsNone(self.v(mode="simulate", steps=[{"tool": "read_doc", "args": {"page": "x"}}]))
        self.assertIsNone(self.v(mode="ai", accept_provider_disclosure=True))

    def test_bad_requests(self):
        self.assertIn("unknown agent", self.v(profile="hr_assistant", mode="steps", steps=[{"tool": "read_doc", "args": {}}]))
        self.assertIn("not available", self.v(task="purchase", mode="steps", steps=[{"tool": "read_doc", "args": {}}]))
        self.assertIn("reserved", self.v(mode="steps", steps=[{"tool": "write_summary", "args": {"_approval": "apr-1"}}]))
        self.assertIn("unknown tool", self.v(mode="steps", steps=[{"tool": "exec_shell", "args": {}}]))
        self.assertIn("confirm", self.v(mode="ai"))
        self.assertIn("1-", self.v(mode="steps", steps=[{"tool": "read_doc", "args": {}}] * 21))
        self.assertIsNotNone(W._validate({**BASE, "mode": "ai", "accept_provider_disclosure": True}, ROLES, False))

    def test_catalogue_has_no_hr_profile_and_lists_unavailable(self):
        c = W.catalogue(ROLES, "E4.3.1")
        self.assertEqual({p["role"] for p in c["profiles"]}, {"procurement", "research"})
        self.assertTrue(c["unavailable"]); self.assertIn("read_workspace_doc", c["tool_spec"])


class TestDocs(unittest.TestCase):
    def setUp(self):
        self.old = W.WS; self.tmp = Path(tempfile.mkdtemp()); W.WS = self.tmp

    def tearDown(self):
        W.WS = self.old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_list_delete(self):
        st, j = W.add_doc("a note.txt", "hello\x00world")
        self.assertEqual(st, 200); self.assertEqual(j["saved"], "a_note.txt")
        self.assertEqual((self.tmp / "a_note.txt").read_text(), "helloworld")   # NUL bytes removed
        self.assertEqual(W.delete_doc("a_note.txt")[0], 200); self.assertEqual(W.list_docs(), [])

    def test_refusals(self):
        self.assertEqual(W.add_doc("../x.txt", "a")[0], 400)
        self.assertEqual(W.add_doc("x.pdf", "a")[0], 400)
        self.assertEqual(W.add_doc("x.txt", "-----BEGIN RSA " + "PRIVATE KEY-----")[0], 422)   # split so the packager's secret scan does not match this file
        self.assertEqual(W.add_doc("x.txt", "a" * (W.MAX_DOC_BYTES + 1))[0], 413)
        self.assertEqual(W.delete_doc("../../etc/passwd")[0], 404)
        for i in range(W.MAX_DOCS):
            W.add_doc(f"d{i}.txt", "x")
        self.assertEqual(W.add_doc("one-more.txt", "x")[0], 409)

    def test_pii_warning(self):
        self.assertIsNotNone(W.add_doc("p.txt", "card 4111 1111 1111 1111")[1]["warning"])


class TestRuns(unittest.TestCase):
    def setUp(self):
        self.fs = FakeStack(); self.old = W.RUNS_DIR; self.tmp = Path(tempfile.mkdtemp()); W.RUNS_DIR = self.tmp

    def tearDown(self):
        W.RUNS_DIR = self.old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_steps_go_only_through_agent_call_and_reserved_args_never_reach_it(self):
        spec = {**BASE, "mode": "steps", "steps": [{"tool": "read_doc", "args": {"page": "x"}}, {"tool": "read_hr_record", "args": {"employee": "g"}}]}
        st, r = W.start(spec, self.fs.H(), ROLES, FakeLLM()); r = wait(r["id"])
        self.assertEqual(r["status"], "done")
        self.assertEqual([c[1] for c in self.fs.calls], ["read_doc", "read_hr_record"])
        self.assertTrue(all(c[0] == "agent_b" for c in self.fs.calls))
        self.assertEqual(r["summary"]["by_response"], {"ALLOW": 1, "DENY": 1})
        res = W.call_tool(W.RUNS[r["id"]], self.fs.H(), "write_summary", {"title": "t", "_approval": "apr-x", "_delegation": "d"}, "you")
        self.assertNotIn("_approval", self.fs.calls[-1][2]); self.assertNotIn("_delegation", self.fs.calls[-1][2])

    def test_provider_failure_stops_cleanly_with_no_tool_calls(self):
        st, r = W.start({**BASE, "mode": "ai", "accept_provider_disclosure": True}, self.fs.H(), ROLES, FakeLLM(exc=RuntimeError("provider HTTP 503")))
        r = wait(r["id"])
        self.assertEqual(self.fs.calls, []); self.assertEqual(r["error"], "provider error")
        self.assertTrue(any(e["kind"] == "error" and "503" in e["what"] for e in r["events"]))

    def test_provider_timeout(self):
        import socket
        st, r = W.start({**BASE, "mode": "ai", "accept_provider_disclosure": True}, self.fs.H(), ROLES, FakeLLM(exc=socket.timeout("timed out")))
        r = wait(r["id"]); self.assertEqual(self.fs.calls, []); self.assertEqual(r["error"], "provider error")

    def test_malformed_model_output_goes_through_the_checkpoint(self):
        turns = [{"content": "", "tool_calls": [{"id": "1", "function": {"name": "read_hr_record", "arguments": "{not json"}},
                                                {"id": "2", "function": {"name": "nonexistent_tool", "arguments": "[]"}}]}, {"content": "final", "tool_calls": []}]
        st, r = W.start({**BASE, "mode": "ai", "accept_provider_disclosure": True}, self.fs.H(), ROLES, FakeLLM(turns=turns))
        r = wait(r["id"])
        self.assertEqual([c[1] for c in self.fs.calls], ["read_hr_record", "nonexistent_tool"])   # both decided by the PEP, args sanitised
        self.assertEqual(self.fs.calls[0][2], {}); self.assertEqual(r["final_answer"], "final")

    def test_turn_limit(self):
        loop = [{"content": "", "tool_calls": [{"id": str(i), "function": {"name": "read_doc", "arguments": "{}"}}]} for i in range(30)]
        st, r = W.start({**BASE, "mode": "ai", "accept_provider_disclosure": True}, self.fs.H(), ROLES, FakeLLM(turns=loop))
        r = wait(r["id"]); self.assertEqual(len(self.fs.calls), W.MAX_AI_TURNS); self.assertIn("turn limit", r["final_answer"])

    def test_busy_console_refuses_the_run(self):
        self.fs.lock.acquire()
        try:
            st, r = W.start({**BASE, "mode": "steps", "steps": [{"tool": "read_doc", "args": {}}]}, self.fs.H(), ROLES, FakeLLM())
            time.sleep(5.5); r = W.get_run(r["id"])
            self.assertEqual(r["status"], "failed"); self.assertEqual(self.fs.calls, [])
        finally:
            self.fs.lock.release()


if __name__ == "__main__":
    unittest.main()
