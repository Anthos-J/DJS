"""Verify S3-isolation/EVIDENCE_MANIFEST.blob.sha256 (blob-based companion of EVIDENCE_MANIFEST.sha256) against the git objects at tag s3-am11-local-repro (read-only).
Line-ending independent: hashes the committed blob (`git show <tag>:<path>`), not the working copy, so a Windows
checkout with core.autocrlf=true does not produce false mismatches. Also reports files changed since the tag.
Usage (from validation/): python tools/verify_manifest.py"""
import hashlib, subprocess, sys

TAG = "s3-am11-local-repro"
rows = []
for line in open("S3-isolation/EVIDENCE_MANIFEST.blob.sha256", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    h, p = line.split(" ", 1)
    rows.append((h, p.lstrip(" *")))
bad, changed = [], []
for h, p in rows:
    blob = subprocess.run(["git", "show", f"{TAG}:{p}"], capture_output=True).stdout
    if hashlib.sha256(blob).hexdigest() != h:
        bad.append(p)
    head = subprocess.run(["git", "show", f"HEAD:{p}"], capture_output=True).stdout
    if head != blob:
        changed.append(p)
print(f"entries={len(rows)} match_at_tag={len(rows) - len(bad)} mismatch_at_tag={len(bad)}")
for p in bad:
    print("  MISMATCH AT TAG:", p)
print(f"changed between tag and HEAD (expected, recorded in later commits): {len(changed)}")
for p in changed:
    print("  changed since tag:", p)
sys.exit(1 if bad else 0)
