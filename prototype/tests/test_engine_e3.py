"""E3 tests (engine_e3). Mature histories throughout, so tool novelty cannot be the control that fires."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mandate.engine_e3 import Engine, ground_value

PROC = ["search_suppliers", "get_prices", "read_supplier_doc", "create_purchase_request", "send_email"]
HR = ["read_hr_record", "read_inbox", "send_email", "update_hr_record"]


class Clock:
    def __init__(self, step=7.0):
        self.t, self.step = 1_800_000_000.0, step
    def __call__(self):
        self.t += self.step
        return self.t


def mature(agent, role, tools, task, instruction="", step=7.0, **kw):
    e = Engine(clock=Clock(step))
    e.register_agent(agent, role, task=task, instruction=instruction, **kw)
    e.learn([{"agent_id": agent, "tool": tools[i % len(tools)], "destination": "internal"} for i in range(100)])
    return e


def F(r):
    return [f["factor"] for f in r["factors"]]


class TestGrounding(unittest.TestCase):
    I = "buy 40 valves from umbrella amount 900"
    def test_exact_money(self):
        self.assertEqual(ground_value("amount", 900, self.I, ""), "grounded")
        self.assertEqual(ground_value("amount", "900.00", self.I, ""), "grounded")
        self.assertEqual(ground_value("amount", "$900", self.I, ""), "grounded")
    def test_substrings_rejected(self):
        for v in (90, 9, 0, "90", 9000):
            self.assertEqual(ground_value("amount", v, self.I, ""), "ungrounded", v)
    def test_quantity_is_not_money(self):
        self.assertEqual(ground_value("amount", 40, self.I, ""), "ungrounded")
    def test_formats(self):
        self.assertEqual(ground_value("amount", "1,200", "pay invoice total $1200.00", ""), "grounded")
        self.assertEqual(ground_value("amount", 1200.5, "budget 1,200.50 usd", ""), "grounded")
        self.assertEqual(ground_value("amount", 1200, "budget 1,200.50 usd", ""), "ungrounded")
    def test_multiple_amounts_ambiguous(self):
        self.assertEqual(ground_value("amount", 900, "buy from umbrella amount 900 or stark amount 450", ""), "ambiguous")
    def test_string_tokens_not_substrings(self):
        self.assertEqual(ground_value("supplier", "umbrella", self.I, ""), "grounded")
        self.assertEqual(ground_value("supplier", "umb", self.I, ""), "ungrounded")
        self.assertEqual(ground_value("to", "carol", "answer carolyn", ""), "ungrounded")


class TestE3(unittest.TestCase):
    def test_spend_limit_and_duplicates(self):
        e = mature("p", "procurement", PROC, "purchase", "buy valves from umbrella amount 900")
        r1 = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 900}})
        r2 = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 900}})
        r3 = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 90}})
        self.assertEqual(r1["response"], "ALLOW"); self.assertEqual(r2["response"], "DENY"); self.assertEqual(r2["control"], "spend_limit")
        self.assertEqual(r3["response"], "DENY")
        self.assertNotIn("novel_tool", F(r1))

    def test_changed_args_after_approval_need_new_approval(self):
        e = mature("p", "procurement", PROC, "purchase", "buy valves from umbrella amount 900 or stark amount 450")
        r = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 900}})
        self.assertEqual(r["response"], "APPROVAL_REQUIRED"); self.assertIn("ambiguous_amount", F(r))
        e.resolve_approval(r["approval_id"], True)
        r2 = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 450}})
        self.assertEqual(r2["response"], "APPROVAL_REQUIRED")          # the approval was for 900, not 450
        r3 = e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "umbrella", "amount": 900}})
        self.assertEqual(r3["response"], "ALLOW")

    def test_fast_scraping_gated_then_denied_and_restricted(self):
        e = mature("p", "procurement", PROC, "price_check", "check valve prices from umbrella", step=7.0)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(90)]
        first_gate = next(i for i, r in enumerate(rs) if r["response"] != "ALLOW")
        self.assertLessEqual(first_gate, 41)
        self.assertIn("read_volume", rs[first_gate]["control"] + "".join(F(rs[first_gate])))
        self.assertTrue(any(r["response"] == "DENY" and r["control"] == "read_volume" for r in rs))
        self.assertIn(e.agents["p"]["status"], ("restricted", "quarantined"))

    def test_slow_scraping_under_rate_ceiling_hits_hourly_budget(self):
        e = mature("p", "procurement", PROC, "price_check", "check valve prices from umbrella", step=20.0)  # 3/min, far below 20/min
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(150)]
        self.assertFalse(any("rate_spike" in F(r) for r in rs))
        self.assertTrue(any(r["response"] != "ALLOW" and "read_volume" in F(r) for r in rs))

    def test_distributed_reads_across_tools_counted_together(self):
        e = mature("p", "procurement", PROC, "supplier_review", "review umbrella documents", step=7.0)
        tools = ["get_prices", "search_suppliers", "read_supplier_doc"]
        rs = [e.decide({"agent_id": "p", "tool": tools[i % 3], "args": {"item": f"x{i}", "doc": f"d{i}"}}) for i in range(60)]
        self.assertTrue(any("read_volume" in F(r) for r in rs))

    def test_legitimate_declared_batch_completes(self):
        e = mature("p", "procurement", PROC, "price_check", "check prices", step=1.0)
        e.assign_task("p", "catalog_refresh", "refresh the umbrella catalogue prices")
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(300)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs), [r["reason"] for r in rs if r["response"] != "ALLOW"][:3])

    def test_task_change_does_not_reset_read_counters(self):
        e = mature("p", "procurement", PROC, "price_check", "check prices", step=7.0)
        for i in range(40):
            e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}})
        e.assign_task("p", "supplier_review", "review umbrella docs")   # not a batch task
        r = e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "x41"}})
        self.assertNotEqual(r["response"], "ALLOW")

    def test_read_budget_extension_by_approval(self):
        e = mature("p", "procurement", PROC, "price_check", "check prices", step=7.0)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(41)]
        ap = rs[-1].get("approval_id"); self.assertIsNotNone(ap)
        e.resolve_approval(ap, True)
        r = e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "x42"}})
        self.assertEqual(r["response"], "ALLOW"); self.assertIn("extended the read budget", r["reason"])
        self.assertTrue(any(x["entry"].get("kind") == "read_budget_extended" for x in e.audit.records))

    def test_hr_object_and_field_authorization(self):
        e = mature("h", "hr_assistant", HR, "inbox", "answer grace about her leave", requester="grace")
        ok = e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace", "fields": "leave"}})
        self.assertEqual(ok["response"], "ALLOW")
        for args, ctl in [({"employee": "dave", "fields": "leave"}, "object_authorization"), ({"employee": "all"}, "object_authorization"),
                          ({"employee": "grace", "fields": "salary"}, "field_authorization"), ({"employee": "grace"}, "field_authorization")]:
            r = e.decide({"agent_id": "h", "tool": "read_hr_record", "args": args})
            self.assertEqual((r["response"], r["control"]), ("DENY", ctl), args)

    def test_hr_cross_employee_copy_blocked_and_legit_update_allowed(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain hr records for grace", subjects=["grace"])
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "dave"}})["response"], "DENY")
        e2 = mature("h", "hr_assistant", HR, "records", "maintain hr records for grace", subjects=["grace"])
        self.assertEqual(e2.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace"}})["response"], "ALLOW")
        self.assertEqual(e2.decide({"agent_id": "h", "tool": "update_hr_record", "args": {"employee": "grace"}})["response"], "ALLOW")

    def test_hr_recipient_must_be_subject(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain hr records for grace", subjects=["grace"])
        e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace"}})
        r = e.decide({"agent_id": "h", "tool": "send_email", "args": {"to": "mallory"}})
        self.assertEqual(r["response"], "APPROVAL_REQUIRED"); self.assertIn("recipient_not_subject", F(r))
        r2 = e.decide({"agent_id": "h", "tool": "send_email", "args": {"to": "grace"}})
        self.assertEqual(r2["response"], "ALLOW")

    def test_bulk_export_only_with_declared_bulk_purpose(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain records for grace", subjects=["grace"])
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "all"}})["response"], "DENY")
        e.assign_task("h", "payroll_batch", "run the declared payroll batch")
        rs = [e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": f"emp{i}"}}) for i in range(50)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs))

    def test_provenance_write_raises_alert(self):
        e = mature("r", "research", ["web_search", "read_doc", "write_summary", "read_doc"], "research", "research pumps")
        e.decide({"agent_id": "r", "tool": "web_search", "args": {"url": "https://q.public.example/p"}, "destination": "q.public.example"})
        w = e.decide({"agent_id": "r", "tool": "write_summary", "args": {"title": "pumps"}})
        self.assertEqual(w["response"], "ALLOW"); self.assertEqual(w.get("provenance_label"), "untrusted"); self.assertTrue(w.get("alert_id"))

    def test_hr_subject_grounded_in_instruction_when_not_declared(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain hr records for grace")
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace"}})["response"], "ALLOW")
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "gra"}})["response"], "DENY")

    def test_consequential_action_after_authz_violation_needs_approval(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain hr records for grace", subjects=["grace"])
        e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "dave"}})
        r = e.decide({"agent_id": "h", "tool": "update_hr_record", "args": {"employee": "grace"}})
        self.assertEqual(r["response"], "APPROVAL_REQUIRED"); self.assertIn("after_authz_violation", F(r))

    def test_leave_reply_to_requester_after_inbox_not_gated(self):
        e = mature("h", "hr_assistant", HR, "inbox", "answer grace about her leave", requester="grace")
        e.decide({"agent_id": "h", "tool": "read_inbox", "args": {}})
        e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace", "fields": "leave"}})
        self.assertEqual(e.decide({"agent_id": "h", "tool": "send_email", "args": {"to": "grace"}})["response"], "ALLOW")
        self.assertNotEqual(e.decide({"agent_id": "h", "tool": "send_email", "args": {"to": "mallory"}})["response"], "ALLOW")


if __name__ == "__main__":
    unittest.main(verbosity=2)
