"""Unit/behaviour tests for the MANDATE drift engine (Part E). Run: python -m unittest discover -s tests -v (needs cedarpy)."""
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mandate.engine import Engine
from mandate import engine as engmod


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0
    def __call__(self):
        self.t += 7.0
        return self.t


def benign_history(agent, tools, n):
    return [{"agent_id": agent, "tool": tools[i % len(tools)], "destination": "internal"} for i in range(n)]


def fresh(history=True):
    e = Engine(clock=Clock())
    e.register_agent("proc-1", "procurement", task="price_check", instruction="check prices for widgets from acme")
    if history:
        e.learn(benign_history("proc-1", ["search_suppliers", "get_prices", "get_prices", "search_suppliers", "read_supplier_doc"], 60))
    return e


class TestEngine(unittest.TestCase):
    def test_01_normal_in_role_allowed(self):
        e = fresh()
        r = e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {"item": "widgets"}})
        self.assertEqual(r["response"], "ALLOW"); self.assertEqual(r["risk_band"], "LOW"); self.assertEqual(r["confidence"], "normal")

    def test_02_out_of_role_with_valid_credential(self):
        e = fresh()
        r = e.decide({"agent_id": "proc-1", "tool": "read_hr_record", "args": {"employee": "all"}, "credential_valid": True})
        self.assertEqual(r["response"], "DENY")
        self.assertIn("out_of_role", [f["factor"] for f in r["factors"]])
        self.assertEqual(e.agents["proc-1"]["status"], "quarantined")
        self.assertTrue(r.get("alert_id"))

    def test_03_indirect_injection_then_exfil(self):
        e = fresh()
        e.decide({"agent_id": "proc-1", "tool": "read_supplier_doc", "args": {"doc": "acme-quote.pdf"}})
        r = e.decide({"agent_id": "proc-1", "tool": "send_email", "args": {"to": "drop@exfil.example"}, "destination": "exfil.example"})
        self.assertEqual(r["response"], "DENY")
        self.assertIn("unapproved_destination", [f["factor"] for f in r["factors"]])
        e2 = fresh()
        e2.decide({"agent_id": "proc-1", "tool": "read_supplier_doc", "args": {"doc": "acme-quote.pdf"}})
        r2 = e2.decide({"agent_id": "proc-1", "tool": "send_email", "args": {"to": "billing@evil.supplier.example"}, "destination": "evil.supplier.example"})
        self.assertEqual(r2["response"], "APPROVAL_REQUIRED")   # allowed domain pattern, but untrusted influence + ungrounded recipient
        codes = [f["factor"] for f in r2["factors"]]
        self.assertIn("untrusted_influence", codes); self.assertIn("ungrounded_consequential", codes)

    def test_04_sensitive_access_and_upload(self):
        e = fresh()
        r = e.decide({"agent_id": "proc-1", "tool": "upload_file", "args": {"url": "https://x.example/u"}, "destination": "x.example"})
        self.assertEqual(r["response"], "DENY")
        e.register_agent("hr-1", "hr_assistant", task="records")
        r2 = e.decide({"agent_id": "hr-1", "tool": "send_email", "args": {"to": "out@ext.example"}, "destination": "ext.example"})
        self.assertEqual(r2["response"], "DENY")                 # HR may not send outside 'internal'

    def test_05_cold_start(self):
        e = fresh(history=False)
        r = e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {}})
        self.assertEqual(r["response"], "ALLOW"); self.assertTrue(r["confidence"].startswith("low"))
        r2 = e.decide({"agent_id": "proc-1", "tool": "read_hr_record", "args": {}})
        self.assertEqual(r2["response"], "DENY")                 # deterministic policy needs no history

    def test_06_legitimate_task_change_vs_undeclared(self):
        e = fresh()
        r = e.decide({"agent_id": "proc-1", "tool": "create_purchase_request", "args": {"supplier": "acme", "amount": 500}})
        self.assertNotEqual(r["response"], "ALLOW")              # undeclared scope change is not silently allowed
        self.assertIn("task_scope_deviation", [f["factor"] for f in r["factors"]])
        e2 = fresh()
        e2.assign_task("proc-1", "purchase", instruction="buy 500 widgets from acme for 500 usd")
        r2 = e2.decide({"agent_id": "proc-1", "tool": "create_purchase_request", "args": {"supplier": "acme", "amount": 500}})
        self.assertEqual(r2["response"], "ALLOW", r2)
        self.assertNotIn("task_scope_deviation", [f["factor"] for f in r2["factors"]])

    def test_07_delegation_attenuation_and_containment(self):
        e = fresh()
        e.register_agent("res-1", "research", task="research")
        with self.assertRaises(PermissionError):
            e.delegate("proc-1", "res-1", ["write_summary"])         # parent does not hold write_summary
        with self.assertRaises(PermissionError):
            e.delegate("proc-1", "res-1", ["web_search"])            # fetch not held by the parent: strict G6 attenuation
        d = e.delegate("proc-1", "res-1", ["read_doc"], task="market_research")
        ok = e.decide({"agent_id": "res-1", "tool": "read_doc", "args": {}, "delegation_id": d["id"]})
        self.assertEqual(ok["response"], "ALLOW"); self.assertEqual(ok["delegation"]["chain"], ["proc-1"])
        esc = e.decide({"agent_id": "res-1", "tool": "web_search", "args": {"url": "https://q.public.example/x"}, "destination": "q.public.example", "delegation_id": d["id"]})
        self.assertEqual(esc["response"], "DENY"); self.assertIn("authority_escalation", [f["factor"] for f in esc["factors"]])
        e2 = fresh(); e2.register_agent("res-1", "research", task="research")
        d2 = e2.delegate("proc-1", "res-1", ["read_doc"])
        e2.set_status("proc-1", "quarantined", "test")
        r = e2.decide({"agent_id": "res-1", "tool": "read_doc", "args": {}, "delegation_id": d2["id"]})
        self.assertEqual(r["response"], "DENY")                  # compromised parent's delegation is suspended

    def test_08_gradual_drift_detected(self):
        e = fresh()
        e.assign_task("proc-1", "supplier_review", instruction="review acme documents")
        hits, quarantined_at = [], None
        for i in range(40):  # slowly shift the mix towards an unusual in-role pattern
            tool = "read_supplier_doc" if i % 3 else "search_suppliers"
            r = e.decide({"agent_id": "proc-1", "tool": tool, "args": {"i": i}})
            hits.append("distribution_drift" in [f["factor"] for f in r["factors"]])
            if e.agents["proc-1"]["status"] != "active" and quarantined_at is None:
                quarantined_at = i
        self.assertTrue(any(hits), "distribution drift never flagged")

    def test_09_mimicry_is_stepped_up_not_silently_allowed(self):
        e = fresh()
        e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {}})
        r = e.decide({"agent_id": "proc-1", "tool": "send_email", "args": {"to": "sales@acme.supplier.example"}, "destination": "acme.supplier.example"})
        self.assertIn(r["response"], ("APPROVAL_REQUIRED", "DENY"))   # G3a: conf-1 data to an external sink needs approval

    def test_10_score_consistency_and_explanation(self):
        a, b = fresh(), fresh()
        ev = {"agent_id": "proc-1", "tool": "create_purchase_request", "args": {"supplier": "zzz", "amount": 9}}
        ra, rb = a.decide(dict(ev)), b.decide(dict(ev))
        self.assertEqual(ra["risk_score"], rb["risk_score"])
        self.assertEqual(ra["risk_score"], min(100, sum(f["points"] for f in ra["factors"])))
        for f in ra["factors"]:
            self.assertTrue(f["evidence"])
        self.assertIn("expected_authority", ra); self.assertIn("reason", ra)

    def test_11_approval_restrict_quarantine_recovery(self):
        e = fresh()
        ev = {"agent_id": "proc-1", "tool": "create_purchase_request", "args": {"supplier": "acme", "amount": 50}}
        r = e.decide(dict(ev)); self.assertEqual(r["response"], "APPROVAL_REQUIRED"); ap = r["approval_id"]
        e.resolve_approval(ap, True, by="owner")
        self.assertEqual(e.decide(dict(ev))["response"], "ALLOW")          # one-time grant consumed
        self.assertEqual(e.decide(dict(ev))["response"], "APPROVAL_REQUIRED")
        e.set_status("proc-1", "quarantined", "manual")
        self.assertEqual(e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {}})["response"], "DENY")
        e.set_status("proc-1", "active", "investigated, benign")
        self.assertEqual(e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {}})["response"], "ALLOW")
        e.set_status("proc-1", "restricted", "manual")
        self.assertEqual(e.decide({"agent_id": "proc-1", "tool": "get_prices", "args": {}})["response"], "ALLOW")   # reads continue
        self.assertEqual(e.decide({"agent_id": "proc-1", "tool": "send_email", "args": {"to": "a"}})["response"], "APPROVAL_REQUIRED")

    def test_12_fail_closed_inputs(self):
        e = fresh()
        for bad in [None, [], {"agent_id": "proc-1"}, {"agent_id": "proc-1", "tool": "get_prices", "args": ["x"]}, {"agent_id": 5, "tool": "x"}]:
            self.assertEqual(e.decide(bad)["response"], "DENY", bad)
        self.assertEqual(e.decide({"agent_id": "ghost", "tool": "get_prices"})["response"], "DENY")
        self.assertEqual(e.decide({"agent_id": "proc-1", "tool": "no_such_tool"})["response"], "DENY")
        self.assertEqual(fresh().decide({"agent_id": "proc-1", "tool": "get_prices", "credential_valid": False})["response"], "DENY")
        old = engmod.HAVE_CEDAR
        try:
            engmod.HAVE_CEDAR = False
            e2 = fresh(); e2.assign_task("proc-1", "purchase", instruction="buy from acme 5")
            r = e2.decide({"agent_id": "proc-1", "tool": "create_purchase_request", "args": {"supplier": "acme", "amount": 5}})
            self.assertEqual(r["response"], "DENY")             # policy engine unavailable -> effectful action refused
        finally:
            engmod.HAVE_CEDAR = old

    def test_13_audit_chain_integrity(self):
        e = fresh()
        for t in ["get_prices", "read_hr_record", "search_suppliers"]:
            e.decide({"agent_id": "proc-1", "tool": t, "args": {}})
        self.assertTrue(e.audit.verify()["ok"])
        recs = json.loads(json.dumps(e.audit.records)); recs[2]["entry"]["response"] = "ALLOW"
        self.assertFalse(e.audit.verify(recs)["ok"])
        recs2 = json.loads(json.dumps(e.audit.records)); del recs2[1]
        self.assertFalse(e.audit.verify(recs2)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
