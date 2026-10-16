"""E4.2 tests (engine_e42): every E4.1 test (two adjusted where E4.2 is stricter by design: L8 scope, R5 gate)
plus focused E4.2 bypass tests. Originally: E4.1 tests (engine_e41): all E4 tests plus the Z4 regression. Originally: E4 tests (engine_e4): E3 tests carried over (two adjusted where E4 is stricter by design) plus E4 cases.
E3 tests Mature histories throughout, so tool novelty cannot be the control that fires."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mandate.engine_e42 import Engine, ground_value

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
        self.assertEqual((r["response"], r["control"]), ("DENY", "recipient_authorization")); self.assertIn("recipient_not_subject", F(r))   # E3: approval
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
        self.assertEqual(w["response"], "APPROVAL_REQUIRED"); self.assertTrue(w.get("alert_id"))   # E4.2 R5: held, not executed-and-labelled

    def test_E4_instruction_names_never_authorize_hr_objects(self):     # E3 allowed this via instruction tokens (Y1 root cause)
        with self.assertRaises(ValueError):                                 # E4.2: undeclared HR scope is refused at assignment (L8)
            mature("h", "hr_assistant", HR, "records", "maintain hr records for grace")

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



class TestE4(unittest.TestCase):
    def test_Y1_colleague_named_in_instruction_cannot_receive_hr_data(self):
        e = mature("h", "hr_assistant", HR, "records", "update grace's record; dave asked about it", subjects=["grace"])
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "grace"}})["response"], "ALLOW")
        r = e.decide({"agent_id": "h", "tool": "send_email", "args": {"to": "dave"}})
        self.assertEqual((r["response"], r["control"]), ("DENY", "recipient_authorization"))
        self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": "dave"}})["response"], "DENY")

    def test_ambiguous_and_variant_names_denied(self):
        e = mature("h", "hr_assistant", HR, "records", "maintain records", subjects=["grace"])
        for x in ("grace.dave", "grace,dave", "gra", "all", "*", ""):
            self.assertEqual(e.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": x}})["response"], "DENY", x)
        e2 = mature("h", "hr_assistant", HR, "records", "maintain records", subjects=["grace"])
        self.assertEqual(e2.decide({"agent_id": "h", "tool": "read_hr_record", "args": {"employee": " Grace "}})["response"], "ALLOW")

    def test_Y2_slow_scraping_under_hourly_budget_hits_distinct_budget(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=30.5)    # ~118/h, under 120/h
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(200)]
        first = next(i for i, r in enumerate(rs) if r["response"] != "ALLOW")
        self.assertEqual(first, 60)                                                            # distinct_per_day = 60
        self.assertIn("distinct objects", " ".join(f["evidence"] for f in rs[first]["factors"]))
        self.assertFalse(any(r["response"] == "ALLOW" for r in rs[61:]))

    def test_repeated_reads_of_same_items_are_not_scraping(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=60.0)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i % 5}"}}) for i in range(110)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs), [r["reason"] for r in rs if r["response"] != "ALLOW"][:2])

    def test_Y3_parallel_agents_share_one_pool(self):
        e = Engine(clock=Clock(5.0))
        for c in ("c1", "c2", "c3"):
            e.register_agent(c, "procurement", task="price_check", instruction="check pump prices")
            e.learn([{"agent_id": c, "tool": PROC[i % 5], "destination": "internal"} for i in range(100)])
        rs = [e.decide({"agent_id": f"c{1 + i % 3}", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(105)]
        first = next(i for i, r in enumerate(rs) if r["response"] != "ALLOW")
        self.assertEqual(first, 40)                                                            # pooled 10-min budget
        ev_ = " ".join(f["evidence"] for f in rs[first]["factors"]); self.assertTrue("shared pool" in ev_ or "across all datasets" in ev_, ev_)

    def test_new_agent_id_does_not_reset_pool(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=5.0)
        for i in range(40):
            e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}})
        e.register_agent("p2", "procurement", task="price_check", instruction="check pump prices")
        self.assertNotEqual(e.decide({"agent_id": "p2", "tool": "get_prices", "args": {"item": "y"}})["response"], "ALLOW")

    def test_delegated_children_share_the_root_principal_pool(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=5.0)
        for c, own in (("r1", "x"), ("r2", "y")):          # children registered under other owners
            e.register_agent(c, "research", owner=own, task="research", instruction="research pumps")
            e.learn([{"agent_id": c, "tool": ["web_search", "read_doc", "write_summary", "read_doc"][i % 4], "destination": "internal"} for i in range(100)])
            e.delegate("p", c, ["read_doc"])
        rs = [e.decide({"agent_id": f"r{1 + i % 2}", "tool": "read_doc", "args": {"page": f"d{i}"}}) for i in range(70)]
        first = next(i for i, r in enumerate(rs) if r["response"] != "ALLOW")
        self.assertEqual(first, 60)                                                            # research per_600s = 60, pooled
        self.assertEqual(e._principal("r1"), "owner")

    def test_declared_parallel_workload_sized_pool(self):
        e = Engine(clock=Clock(1.0))
        for c in ("c1", "c2", "c3", "c4"):
            e.register_agent(c, "procurement", task="parallel_catalog_refresh", instruction="refresh catalogue prices")
        rs = [e.decide({"agent_id": f"c{1 + i % 4}", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(800)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs), [r["reason"] for r in rs if r["response"] != "ALLOW"][:2])

    def test_restart_rehydrates_counters_and_spend(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
        clk = Clock(5.0)
        e = Engine(clock=clk, audit_path=path)
        e.register_agent("p", "procurement", task="purchase", instruction="buy pumps from hooli amount 900")
        self.assertEqual(e.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "hooli", "amount": 900}})["response"], "ALLOW")
        for i in range(40):
            e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}})
        e2 = Engine(clock=clk, audit_path=path)                                     # restart
        e2.register_agent("p", "procurement", task="purchase", instruction="buy pumps from hooli amount 900")
        self.assertNotEqual(e2.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "y"}})["response"], "ALLOW")
        self.assertEqual(e2.decide({"agent_id": "p", "tool": "create_purchase_request", "args": {"supplier": "hooli", "amount": 900}})["response"], "DENY")
        self.assertTrue(any(r["entry"].get("kind") == "counters_rehydrated" for r in e2.audit.records))

    def test_broken_audit_chain_refuses_start(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
        e = Engine(clock=Clock(), audit_path=path); e.register_agent("p", "procurement", task="price_check")
        e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "x"}})
        lines = open(path, encoding="utf-8").read().splitlines(); lines.pop(0)
        open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        with self.assertRaises(RuntimeError):
            Engine(clock=Clock(), audit_path=path)

    def test_concurrent_reads_counted_exactly(self):
        import threading
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=7.0)
        out = []
        def worker(k):
            for i in range(20):
                out.append(e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"t{k}-{i}"}})["response"])
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(5)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(out.count("ALLOW"), 40)                                               # never more than the budget


class TestE41(unittest.TestCase):
    def test_Z4_unkeyed_argument_aliasing_counts_as_distinct(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=30.5)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "pumps", "supplier": f"s{i}"}}) for i in range(100)]
        self.assertEqual(next(i for i, r in enumerate(rs) if r["response"] != "ALLOW"), 60)

    def test_whitespace_case_variants_are_the_same_object(self):
        e = mature("p", "procurement", PROC, "price_check", "check pump prices", step=60.0)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": v}}) for v in ["Pumps", " pumps", "PUMPS "] * 40]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs))


import json as _json, shutil, subprocess, tempfile
from mandate.state_e42 import StateError

RES = ["web_search", "read_doc", "write_summary", "read_doc"]
DEV = ["read_logs", "query_metrics", "read_logs", "restart_service"]


def stateful(tmp, clk=None, **kw):
    return Engine(clock=clk or Clock(), audit_path=os.path.join(tmp, "audit.jsonl"), state_dir=os.path.join(tmp, "state"), **kw)


class TestE42Poisoning(unittest.TestCase):          # R5
    def test_poisoned_trusted_store_write_held_and_not_persisted(self):
        e = mature("r", "research", RES, "research", "research pumps")
        e.decide({"agent_id": "r", "tool": "web_search", "args": {"url": "https://q.public.example/p"}, "destination": "q.public.example"})
        w = e.decide({"agent_id": "r", "tool": "write_summary", "args": {"title": "pumps"}})
        self.assertEqual((w["response"], w["control"]), ("APPROVAL_REQUIRED", "untrusted_store_write"))
        self.assertNotIn(("wiki", "pumps"), e.store_labels)                                  # nothing entered the trusted store
        e.register_agent("c", "research", task="research", instruction="read the pumps page")
        e.learn([{"agent_id": "c", "tool": RES[i % 4], "destination": "internal"} for i in range(100)])
        rc = e.decide({"agent_id": "c", "tool": "read_doc", "args": {"page": "pumps"}})
        self.assertNotEqual(rc.get("provenance_label"), "untrusted (inherited)")             # no propagation from a pending write
        e.resolve_approval(w["approval_id"], True)
        w2 = e.decide({"agent_id": "r", "tool": "write_summary", "args": {"title": "pumps"}})
        self.assertEqual(w2["response"], "ALLOW"); self.assertEqual(e.store_labels[("wiki", "pumps")], "trusted (owner-approved)")

    def test_untainted_write_allowed(self):
        e = mature("r", "research", RES, "research", "research pumps")
        e.decide({"agent_id": "r", "tool": "read_doc", "args": {"page": "pumps"}})
        self.assertEqual(e.decide({"agent_id": "r", "tool": "write_summary", "args": {"title": "pumps"}})["response"], "ALLOW")


class TestE42Restart(unittest.TestCase):            # R6
    def test_restart_after_untrusted_logs_needs_corroboration(self):
        e = mature("d", "devops", DEV, "operate", "keep service api healthy; restart api if needed")
        e.decide({"agent_id": "d", "tool": "read_logs", "args": {"service": "api"}})
        r = e.decide({"agent_id": "d", "tool": "restart_service", "args": {"service": "api"}})
        self.assertEqual((r["response"], r["control"]), ("APPROVAL_REQUIRED", "uncorroborated_trigger"))

    def test_corroborated_first_restart_allowed_repeats_gated(self):
        e = mature("d", "devops", DEV, "operate", "keep service api healthy; restart api if needed")
        e.decide({"agent_id": "d", "tool": "read_logs", "args": {"service": "api"}})
        e.decide({"agent_id": "d", "tool": "query_metrics", "args": {"service": "api"}})
        self.assertEqual(e.decide({"agent_id": "d", "tool": "restart_service", "args": {"service": "api"}})["response"], "ALLOW")
        later = [e.decide({"agent_id": "d", "tool": "restart_service", "args": {"service": "api"}})["response"] for _ in range(3)]
        self.assertNotIn("ALLOW", later[1:])

    def test_new_untrusted_input_invalidates_corroboration(self):
        e = mature("d", "devops", DEV, "operate", "keep service api healthy")
        e.decide({"agent_id": "d", "tool": "query_metrics", "args": {"service": "api"}})
        e.decide({"agent_id": "d", "tool": "read_logs", "args": {"service": "api"}})
        self.assertNotEqual(e.decide({"agent_id": "d", "tool": "restart_service", "args": {"service": "api"}})["response"], "ALLOW")

    def test_restart_without_untrusted_input_allowed(self):
        e = mature("d", "devops", DEV, "operate", "keep service api healthy")
        e.decide({"agent_id": "d", "tool": "query_metrics", "args": {"service": "api"}})
        self.assertEqual(e.decide({"agent_id": "d", "tool": "restart_service", "args": {"service": "api"}})["response"], "ALLOW")


class TestE42CrossPrincipal(unittest.TestCase):     # Z2
    def _engine(self, owners, step=5.0):
        e = Engine(clock=Clock(step))
        for i, o in enumerate(owners):
            e.register_agent(f"p{i}", "procurement", owner=o, task="price_check", instruction="check pump prices")
            e.learn([{"agent_id": f"p{i}", "tool": PROC[j % 5], "destination": "internal"} for j in range(100)])
        return e

    def test_three_owners_bounded_by_dataset_quota(self):
        e = self._engine(["o1", "o2", "o3"])
        rs = [e.decide({"agent_id": f"p{i % 3}", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(120)]
        self.assertEqual(sum(r["response"] == "ALLOW" for r in rs), 60)                      # datasets.price_list.per_600s
        self.assertIn("dataset_fair_share", [f["factor"] for f in rs[60]["factors"]])

    def test_light_tenant_not_denied_by_heavy_tenant(self):
        e = self._engine(["heavy", "light", "new"])
        for i in range(40):
            e.decide({"agent_id": "p0", "tool": "get_prices", "args": {"item": f"h{i}"}})
        for i in range(20):
            e.decide({"agent_id": "p1", "tool": "get_prices", "args": {"item": f"l{i}"}})
        self.assertEqual(e.decide({"agent_id": "p2", "tool": "get_prices", "args": {"item": "n0"}})["response"], "ALLOW")
        self.assertNotEqual(e.decide({"agent_id": "p0", "tool": "get_prices", "args": {"item": "h99"}})["response"], "ALLOW")

    def test_declared_batch_not_gated_by_dataset_quota(self):
        e = Engine(clock=Clock(1.0))
        for i, o in enumerate(["o1", "o2"]):
            e.register_agent(f"b{i}", "procurement", owner=o, task="catalog_refresh", instruction="refresh catalogue")
        rs = [e.decide({"agent_id": f"b{i % 2}", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(300)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs))


class TestE42State(unittest.TestCase):              # L3 / L12 / L13
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _seed(self, clk):
        e = stateful(self.tmp, clk)
        e.register_agent("p", "procurement", task="price_check", instruction="check pump prices")
        e.learn([{"agent_id": "p", "tool": PROC[i % 5], "destination": "internal"} for i in range(100)])
        for i in range(40):
            e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}})
        return e

    def _close(self, e):
        e.store._lockfh.close()

    def test_restart_restores_status_approvals_baseline_and_counters(self):
        clk = Clock(5.0); e = self._seed(clk)
        r = e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "y"}}); ap = r["approval_id"]
        e.set_status("p", "quarantined", "test"); n = e.agent_base["p"]["n"]; self._close(e)
        e2 = stateful(self.tmp, clk)
        self.assertEqual(e2.agents["p"]["status"], "quarantined"); self.assertIn(ap, e2.approvals); self.assertEqual(e2.agent_base["p"]["n"], n)
        self.assertEqual(e2.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "z"}})["response"], "DENY")

    def test_second_process_refused(self):
        e = self._seed(Clock())
        code = ("import sys; sys.path.insert(0, '.'); from mandate.engine_e42 import Engine\n"
                f"try:\n    Engine(audit_path={os.path.join(self.tmp, 'audit.jsonl')!r}, state_dir={os.path.join(self.tmp, 'state')!r})\n"
                "    print('STARTED')\nexcept Exception as x:\n    print('REFUSED', x)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), "..")).stdout
        self.assertIn("REFUSED", out); self.assertIn("locked", out)
        self._close(e)

    def _refused_after(self, mutate):
        clk = Clock(5.0); e = self._seed(clk); self._close(e)
        mutate(os.path.join(self.tmp, "audit.jsonl"))
        with self.assertRaises(StateError):
            stateful(self.tmp, clk)

    def test_audit_deleted_refused(self):
        self._refused_after(os.remove)

    def test_audit_truncated_refused(self):
        def trunc(p):
            L = open(p, encoding="utf-8").read().splitlines(); open(p, "w", encoding="utf-8").write("\n".join(L[:-5]) + "\n")
        self._refused_after(trunc)

    def test_audit_tampered_refused(self):
        clk = Clock(5.0); e = self._seed(clk); self._close(e)
        p = os.path.join(self.tmp, "audit.jsonl"); L = open(p, encoding="utf-8").read().splitlines()
        i = next(k for k, l in enumerate(L) if '"kind": "decision"' in l)
        L[i] = L[i].replace("within mandate", "within mandat3"); open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
        with self.assertRaises((StateError, RuntimeError)):
            stateful(self.tmp, clk)

    def test_audit_replaced_with_fresh_log_refused(self):
        def replace(p):
            os.remove(p); Engine(audit_path=p).register_agent("p", "procurement", task="price_check")
        self._refused_after(replace)

    def test_torn_uncommitted_final_write_recovered(self):
        clk = Clock(5.0); e = self._seed(clk); self._close(e)
        with open(os.path.join(self.tmp, "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"seq": 99999, "partial')
        e2 = stateful(self.tmp, clk)
        self.assertIn("torn_final_audit_write_dropped", e2.store.findings)
        self.assertNotEqual(e2.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "y"}})["response"], "ALLOW")

    def test_torn_committed_write_refused(self):
        def tear(p):
            L = open(p, encoding="utf-8").read().splitlines(); L[-1] = L[-1][:20]
            open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
        self._refused_after(tear)

    def test_checkpoint_missing_refused(self):
        clk = Clock(5.0); e = self._seed(clk); self._close(e)
        os.remove(os.path.join(self.tmp, "state", "checkpoint.json"))
        with self.assertRaises(StateError):
            stateful(self.tmp, clk)

    def test_anchor_detects_deletion_of_both_log_and_state(self):
        anchor = os.path.join(tempfile.mkdtemp(), "anchor.json"); clk = Clock(5.0)
        e = stateful(self.tmp, clk, anchor_path=anchor); e.register_agent("p", "procurement", task="price_check"); self._close(e)
        os.remove(os.path.join(self.tmp, "audit.jsonl")); shutil.rmtree(os.path.join(self.tmp, "state"))
        with self.assertRaises(StateError):
            stateful(self.tmp, clk, anchor_path=anchor)

    def test_hmac_checkpoint_forgery_refused(self):
        clk = Clock(5.0)
        e = stateful(self.tmp, clk, state_key="k1"); e.register_agent("p", "procurement", task="price_check"); self._close(e)
        p = os.path.join(self.tmp, "state", "checkpoint.json"); d = _json.load(open(p))
        d["body"]["state"]["agents"]["p"]["status"] = "active"; d["body"]["seq"] = d["body"]["seq"]; _json.dump(d, open(p, "w"))
        e.store._lockfh.close()
        d["body"]["state"]["agents"]["p"]["status"] = "quarantined"; _json.dump(d, open(p, "w"))
        with self.assertRaises(StateError):
            stateful(self.tmp, clk, state_key="k1")

    def test_recovery_mode_requires_approval_until_ack(self):
        clk = Clock(5.0); e = self._seed(clk); self._close(e)
        os.remove(os.path.join(self.tmp, "audit.jsonl"))
        e2 = stateful(self.tmp, clk, recovery=True)
        e2.register_agent("p", "procurement", task="price_check", instruction="check pump prices")
        r = e2.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "q"}})
        self.assertEqual((r["response"], r["control"]), ("APPROVAL_REQUIRED", "recovery_mode"))
        e2.ack_recovery(note="owner reviewed")
        self.assertEqual(e2.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": "q2"}})["response"], "ALLOW")
        self.assertTrue(any(x["entry"].get("kind") == "recovery_mode_started" for x in e2.audit.records))


class TestE42ScopeAndAlerts(unittest.TestCase):     # L8 / L6
    def test_hr_task_requires_declared_scope(self):
        e = Engine(clock=Clock())
        with self.assertRaises(ValueError):
            e.register_agent("h", "hr_assistant", task="records", instruction="maintain hr records for grace")
        with self.assertRaises(ValueError):
            e.register_agent("h", "hr_assistant", task="records", subjects=["grace,dave"])
        e.register_agent("h", "hr_assistant", task="records", subjects=["grace"])
        e.register_agent("h2", "hr_assistant", task="payroll_batch")                           # bulk purpose needs no subject

    def test_repeated_drift_alerts_aggregate(self):
        e = mature("p", "procurement", PROC, "catalog_refresh", "refresh catalogue", step=1.0)
        rs = [e.decide({"agent_id": "p", "tool": "get_prices", "args": {"item": f"x{i}"}}) for i in range(200)]
        self.assertTrue(all(r["response"] == "ALLOW" for r in rs))
        self.assertLessEqual(sum(bool(r.get("alert_id")) for r in rs), 2)
        self.assertGreater(sum(bool(r.get("aggregated_into")) for r in rs), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
