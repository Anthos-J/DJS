"""E4.2 persistence and recovery for security-critical control-plane state (L3 / L12 / L13).

* Single writer: an exclusive OS lock on <state_dir>/lock. A second control-plane process on the same state refuses
  to start, so two processes cannot keep separate budgets (no multi-replica support is claimed).
* Checkpoint: <state_dir>/checkpoint.json, written atomically (tmp + fsync + os.replace) after every state change.
  It holds agent status, approvals, delegations, baselines, provenance labels and budget extensions, plus the audit
  sequence number and head hash it corresponds to. With MANDATE_STATE_KEY set, it is HMAC-SHA256 signed.
* Optional anchor: a second copy of {seq, head} in a separate location (MANDATE_STATE_ANCHOR), so deleting the state
  directory and the audit log together is detected.
* Start-up checks (fail closed): HMAC; audit hash chain; the audit must still contain the checkpointed record with
  the checkpointed hash (deleted / truncated / replaced history is refused); a torn final audit line from an
  interrupted write is dropped ONLY if the checkpoint does not cover it. A refused start can be overridden only by
  the owner's explicit recovery mode, in which every read and effect needs approval until the owner acknowledges.
* NOT tamper-proof: an attacker who controls the audit log, the checkpoint, the anchor AND the HMAC key can forge a
  consistent history. That boundary is documented in the limitations register."""
import hashlib, hmac, json, os


class StateError(RuntimeError):
    pass


def _lock(fh):
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:                       # Windows host (tests run in the Linux container)
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)


class StateStore:
    def __init__(self, state_dir, audit_path, key=None, anchor_path=None):
        os.makedirs(state_dir, exist_ok=True)
        self.dir, self.audit_path, self.anchor = state_dir, audit_path, anchor_path
        self.key = key.encode() if isinstance(key, str) and key else None
        self.ckpt_path = os.path.join(state_dir, "checkpoint.json")
        self._lockfh = open(os.path.join(state_dir, "lock"), "a+")
        try:
            _lock(self._lockfh)
        except OSError:
            raise StateError("state directory is locked by another control-plane process (single-writer)")
        self.findings = []

    def _sig(self, body):
        return hmac.new(self.key, json.dumps(body, sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest() if self.key else None

    def _read_json(self, path):
        if not path or not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if self.key and not hmac.compare_digest(str(d.get("sig")), str(self._sig(d.get("body")))):
            raise StateError(f"signature check failed for {os.path.basename(path)}")
        return d["body"]

    def preflight(self):
        """Validate (and only if provably safe, repair) the audit log against the checkpoint. Returns the checkpoint body
        or None. Raises StateError when security history is missing or inconsistent."""
        ck = self._read_json(self.ckpt_path)
        an = self._read_json(self.anchor)
        recs, torn = [], False
        if self.audit_path and os.path.exists(self.audit_path):
            with open(self.audit_path, encoding="utf-8") as f:
                lines = [l for l in f.read().split("\n") if l.strip()]
            for i, l in enumerate(lines):
                try:
                    recs.append(json.loads(l))
                except json.JSONDecodeError:
                    if i != len(lines) - 1:
                        raise StateError(f"audit log corrupted at line {i + 1} (not a torn final write)")
                    torn = True
        ref = ck or an
        if torn:
            if ref is not None and ref["seq"] >= len(recs):
                raise StateError("torn audit record is covered by the checkpoint: committed history lost")
            tmp = self.audit_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, default=str) + "\n" for r in recs)); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.audit_path)
            self.findings.append("torn_final_audit_write_dropped")
        if ref is not None:
            if ref["seq"] >= len(recs) or recs[ref["seq"]]["hash"] != ref["head"]:
                which = "checkpoint" if ck else "anchor (checkpoint missing)"
                raise StateError(f"audit history missing or replaced: {which} expects record {ref['seq']} with head {ref['head'][:12]}, "
                                 f"audit has {len(recs)} records")
        if an is not None and ck is not None and an["seq"] > ck["seq"]:
            raise StateError("checkpoint older than the anchor: checkpoint rolled back")
        if ck is None and recs:
            raise StateError("audit log present but checkpoint missing: security state (status, approvals) cannot be restored")
        return ck

    def save(self, seq, head, state):
        body = {"seq": seq, "head": head, "state": state}
        for path, b in ((self.ckpt_path, body), (self.anchor, {"seq": seq, "head": head})):
            if not path:
                continue
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"body": b, "sig": self._sig(b)}, f, default=str); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
