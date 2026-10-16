# Handoff audit (16 Oct 2026)

Audited commit: `2d4b4a09e5aeb7d8bc08cc75a8e6450cc7dfc5a1`. The working tree was clean at the start. Read-only checks, plus documentation and tooling added in the handoff commit. **No test was rerun, no historical evidence was modified, and Docker data was not touched.**

| Check | Result |
|---|---|
| `bash -n` on 13 run/build scripts | all OK |
| `py_compile` on all harness and driver Python | all OK. **Side effect, corrected:** it overwrote 14 *tracked* `__pycache__/*.pyc` files. They were restored with `git checkout -- <file>`, and the tree is clean again. `.gitignore` now ignores untracked bytecode |
| AM11 static check (`cell_policy.py static`) on all 5 deployable compose files (S3 canonical, S7, S5, S6, S8) | exit 0 for all |
| Checklist commands exist in the scripts | all 7 found |
| Checklist expected results vs latest recorded runs | all match: S3 regression 0 failing; S1 12 PASS + 12 RECORDED; S7 38 PASS; S5 v2 27 PASS + DNS PASS; S6 33 PASS + 1 BLOCKED; S8 v2 27 PASS; S4a hashes `e69d6d61` / `acb29d3e` |
| `sha256sum -c S3-isolation/EVIDENCE_MANIFEST.sha256` (original machine) | 294/297 OK. The 3 FAILED files are those changed in later recorded commits. Output: `manifest_check_original_machine.txt` |
| The same manifest vs git blobs at tag `s3-am11-local-repro` | 196 match as stored (LF); 92 match only in CRLF form; 9 have mixed line endings. The manifest hashed Windows working-copy bytes, so it **cannot be verified on a fresh clone**. Added the companion `S3-isolation/EVIDENCE_MANIFEST.blob.sha256` (from tag blobs) and `tools/verify_manifest.py`: **297/297 match**. The original manifest is unchanged |

**Checklist corrections made:**
- unsigned tag (`git tag -v` cannot be used);
- `images/agentdojo/build.sh` has the same base-ID lock as `images/mitm/build.sh`;
- blob-based manifest verification;
- `PYTHONDONTWRITEBYTECODE=1`;
- exact S1 counts;
- the fresh-VM option, recorded as such;
- optional S2;
- a note that transitive dependencies are not hash-pinned.
