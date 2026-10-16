"""Build the hackathon submission ZIP from an explicit file list (source, dependencies, selected evidence, demo artifacts).
Writes ../submission/MANDATE_E4.2.1_submission.zip plus a .sha256, with MANIFEST.sha256 inside the ZIP.
Refuses to package anything that looks like a private key or a credential. Usage: python demo/make_submission.py"""
import glob, hashlib, os, re, sys, zipfile
from pathlib import Path

P = Path(__file__).resolve().parent.parent          # validation/prototype
V = P.parent                                         # validation/
OUT = V / "submission"; OUT.mkdir(exist_ok=True)
ZIP = OUT / "MANDATE_E4.2.1_submission.zip"
ROOT = "MANDATE_E4.2.1"
SKIP = re.compile(r"(__pycache__|\.pyc$|\.console\.pid$|\.meta\.json$|console\.log$|/demo/runs/|build\.log$)")

files = []
def add(pattern, base=V):
    hits = sorted(glob.glob(str(base / pattern), recursive=True))
    if not hits:
        sys.exit(f"missing required input: {pattern}")
    files.extend(Path(h) for h in hits if Path(h).is_file())

# --- source (prototype)
for p in ["prototype/*.md", "prototype/*.sha256", "prototype/compose.yaml", "prototype/run_prototype.sh", "prototype/mandate/*.py",
          "prototype/control/**/*", "prototype/console/*.py", "prototype/console/static/*", "prototype/console/tests/*.py",
          "prototype/pep/*.py", "prototype/config/*.json", "prototype/demo/*.sh", "prototype/demo/*.py", "prototype/e2e/e2e_driver.py",
          "prototype/tests/*.py", "prototype/tests/*.sh", "prototype/eval/*.py", "prototype/eval/*.md", "prototype/docs/*"]:
    add(p)
# --- dependencies used by compose / the launcher / the image
for p in ["S2-cedar/config/*", "S7-binding/config/*", "S7-binding/harness/*.py", "S3-isolation/harness/cell_policy.py",
          "images/spike-py312/Dockerfile", "images/spike-py312/requirements.txt", "images/spike-py312/fetch_tools.py",
          "images/spike-py312/image_manifest.txt", "images/spike-py312/lock/*", "tools/*", "WORKFLOW_AMENDMENT_OA1.md", "STATUS.md", "PRB_TRACEABILITY.md"]:
    add(p)
# --- selected evidence (what the console's Results/Diagnostics pages read, plus final verification runs)
for p in ["prototype/eval/runs/20261016T1800-E4.2.1-h5eval-s95x-run*/summary.json", "prototype/eval/runs/20261016T1800-E4.2.1-h5eval-s95x-run*/stdout.log",
          "prototype/eval/runs/20261016T1700-E4.1-h5eval-run1/summary.json", "prototype/eval/runs/20261016T1700-E4.2-h5eval-run1/summary.json",
          "prototype/eval/runs/20261016T1500-E2-h3eval-run1/outcome_audit.json", "prototype/eval/runs/20261016T1500-E3-h3eval-run1/outcome_audit.json",
          "prototype/eval/runs/20261016T1700-E3-h4eval-run1/outcome_audit.json", "prototype/eval/runs/20261016T1700-E4-h4eval-run1/outcome_audit.json",
          "prototype/eval/runs/20261016T1830-E421-redteam5/*.json", "prototype/eval/runs/20261016T1830-E421-redteam5/stdout.log",
          "prototype/e2e/runs/20261016T172125-e2e/*", "prototype/e2e/runs/20261016T182547-e2e/*", "prototype/e2e/runs/20261016T182817-e2e/*",
          "prototype/tests/runs/**/*", "prototype/console/tests/runs/**/*",
          "prototype/submission_assets/**/*"]:
    add(p)

files = sorted({f for f in files if not SKIP.search(f.as_posix())})
secret = re.compile(rb"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----|sk-ant-|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30}")
bad = [f for f in files if secret.search(f.read_bytes())]
if bad:
    sys.exit(f"refusing to package possible secrets: {bad}")
man = []
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in files:
        rel = f.relative_to(V).as_posix(); data = f.read_bytes()
        if f.suffix in (".sh", ".py", ".md", ".yaml", ".json", ".txt", ".cedar", ".conf", ".js", ".css", ".html", ".svg", ".sha256", ".cedarschema", ".log", ".jsonl"):
            data = data.replace(b"\r\n", b"\n")      # LF for bash/docker on any checkout setting
        z.writestr(f"{ROOT}/{rel}", data)
        man.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    z.writestr(f"{ROOT}/MANIFEST.sha256", "\n".join(man) + "\n")
    z.writestr(f"{ROOT}/README.md", (P / "SUBMISSION_README.md").read_text(encoding="utf-8"))
h = hashlib.sha256(ZIP.read_bytes()).hexdigest()
(OUT / (ZIP.name + ".sha256")).write_text(f"{h}  {ZIP.name}\n")
print(f"wrote {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB, {len(files)} files) sha256 {h}")
