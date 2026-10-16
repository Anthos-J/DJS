"""Append-only, hash-chained audit log. Each record carries prev_hash and its own hash over the canonical JSON;
verify() recomputes the chain so any edit, deletion or reordering is detected."""
import hashlib, json, os, threading, time


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, path=None):
        self.path, self.records, self.lock = path, [], threading.Lock()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.records = [json.loads(l) for l in f if l.strip()]

    @staticmethod
    def _h(body):
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def append(self, entry):
        with self.lock:
            prev = self.records[-1]["hash"] if self.records else self.GENESIS
            body = {"seq": len(self.records), "t": time.time(), "prev_hash": prev, "entry": entry}
            rec = {**body, "hash": self._h(body)}
            self.records.append(rec)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
            return rec

    def verify(self, records=None):
        recs = self.records if records is None else records
        prev = self.GENESIS
        for i, r in enumerate(recs):
            body = {k: r[k] for k in ("seq", "t", "prev_hash", "entry")}
            if r["seq"] != i or r["prev_hash"] != prev or self._h(body) != r["hash"]:
                return {"ok": False, "broken_at": i}
            prev = r["hash"]
        return {"ok": True, "records": len(recs), "head": prev}
