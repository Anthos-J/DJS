"""Offline verifier for a MANDATE incident evidence pack (Python standard library only; no MANDATE code needed).
Usage: python verify_evidence_pack.py <pack.json>      exit 0 = VERIFIED, 1 = FAILED
Checks:
  1. pack digest: sha256 of the canonical pack body equals pack_sha256 (the file was not edited after export)
  2. audit chain: every record's hash is recomputed exactly as mandate/audit.py does, and links prev_hash -> hash from
     the genesis value; sequence numbers are contiguous from 0
  3. the decision is IN the chain: the last record is the decision's audit entry, with the same tool, response and
     reason as the exported decision
  4. the effect claim is consistent: ALLOW decisions may have tool-server effects; DENY / APPROVAL_REQUIRED decisions
     must have none recorded for that decision id
What this proves and does not prove: the exported records are internally consistent and were not altered after the
chain was written up to the exported head. Packs are not signed: anyone holding the whole chain could build a
consistent forgery. Compare `audit_head` with the control plane's live head (Audit explorer) to tie it to a system."""
import hashlib, json, sys

GENESIS = "0" * 64


def h(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def verify(pack):
    out = []
    ok = lambda name, cond, detail="": out.append((name, bool(cond), detail)) or bool(cond)
    body = {k: v for k, v in pack.items() if k != "pack_sha256"}
    ok("pack digest matches (not edited after export)", h(body) == pack.get("pack_sha256"))
    recs = pack["audit"]["records"]; prev = GENESIS; chain_ok = True; where = ""
    for i, r in enumerate(recs):
        b = {k: r[k] for k in ("seq", "t", "prev_hash", "entry")}
        if r["seq"] != i or r["prev_hash"] != prev or h(b) != r["hash"]:
            chain_ok, where = False, f"broken at record {i}"; break
        prev = r["hash"]
    ok("audit hash chain recomputes from genesis", chain_ok, where or f"{len(recs)} records, head {prev[:16]}…")
    ok("chain head equals the exported audit_head", prev == pack["audit"]["audit_head"])
    d, last = pack["decision"], (recs[-1]["entry"] if recs else {})
    ok("the decision is the last record in the chain", last.get("kind") == "decision" and last.get("decision_id") == d["decision_id"])
    ok("decision fields match its audit record", all(last.get(k) == d.get(k) for k in ("tool", "response", "reason", "agent_id")))
    eff = pack["tool_server_effects"]
    if d["response"] == "ALLOW":
        ok("effect claim consistent (ALLOW: effects may exist)", True, f"{len(eff)} effect(s)")
    else:
        ok(f"effect claim consistent ({d['response']}: no tool-server effect for this decision)", len(eff) == 0, f"{len(eff)} effect(s)")
    return out


if __name__ == "__main__":
    pack = json.load(open(sys.argv[1], encoding="utf-8"))
    res = verify(pack)
    for name, good, detail in res:
        print(f"{'PASS' if good else 'FAIL'}  {name}  {detail}")
    allok = all(g for _, g, _ in res)
    print("VERIFIED" if allok else "FAILED"); sys.exit(0 if allok else 1)
