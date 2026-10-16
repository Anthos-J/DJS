"""Automated evidence-integrity verification (OA-1 condition 5). Read-only.
  python tools/verify_evidence.py generate   -> writes EVIDENCE_MANIFEST_ALL.blob.sha256 from the committed git objects
                                                of every file under a runs/ directory, plus frozen inputs (HEAD)
  python tools/verify_evidence.py verify     -> recomputes from git objects at HEAD and reports added / missing /
                                                changed evidence; also runs tools/verify_manifest.py (S3 tag manifest)
Blob-based, so line-ending settings do not matter. Evidence files are expected to be append-only: a CHANGED or
MISSING entry is a finding to investigate (earlier runs must never be rewritten)."""
import hashlib, subprocess, sys

MAN = "EVIDENCE_MANIFEST_ALL.blob.sha256"


def tracked():
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
    keep = ("/runs/", "prototype/eval/FROZEN", "S4a-agentdojo/config/", "prototype/config/")
    return sorted(f for f in files if any(k in f for k in keep) and "__pycache__" not in f and not f.endswith("/LATEST"))


def blob(rev, path):
    return subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True).stdout


def main(mode):
    if mode == "generate":
        rows = [f"{hashlib.sha256(blob('HEAD', p)).hexdigest()}  {p}" for p in tracked()]
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        open(MAN, "w", encoding="utf-8", newline="\n").write(f"# evidence manifest from git objects at {head}\n" + "\n".join(rows) + "\n")
        print(f"wrote {MAN}: {len(rows)} files"); return 0
    want = {}
    for l in open(MAN, encoding="utf-8"):
        if l.strip() and not l.startswith("#"):
            h, p = l.rstrip("\n").split("  ", 1); want[p] = h
    now = set(tracked()); changed, missing = [], []
    for p, h in want.items():
        if p not in now:
            missing.append(p)
        elif hashlib.sha256(blob("HEAD", p)).hexdigest() != h:
            changed.append(p)
    added = sorted(now - set(want))
    print(f"manifest entries={len(want)} unchanged={len(want) - len(changed) - len(missing)} changed={len(changed)} missing={len(missing)} new_since_manifest={len(added)}")
    for p in changed:
        print("  CHANGED:", p)
    for p in missing:
        print("  MISSING:", p)
    r = subprocess.run([sys.executable, "tools/verify_manifest.py"], capture_output=True, text=True)
    print("S3 tag manifest:", r.stdout.splitlines()[0] if r.stdout else r.stderr[:200])
    return 1 if changed or missing or r.returncode else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "verify"))
