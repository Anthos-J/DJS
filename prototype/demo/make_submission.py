"""Build the hackathon submission ZIP from an explicit file list (source, dependencies, selected evidence, demo artifacts).
Writes ../submission/MANDATE_E4.3.1_submission.zip plus a .sha256, with MANIFEST.sha256 inside the ZIP, and the separate
model archive ../submission/MANDATE_E4.3_injection_model.zip (+ .sha256): model.onnx is ~568 MB and its training data
includes datasets without a declared licence, so it is delivered beside the code, not inside it (see MODEL_RESTORE.md).
The model archive is only written if model.onnx matches the hash frozen in FROZEN_E43.sha256.
Refuses to package anything that looks like a private key or a credential. Usage: python demo/make_submission.py"""
import glob, hashlib, os, re, sys, zipfile
from pathlib import Path

P = Path(__file__).resolve().parent.parent          # validation/prototype
V = P.parent                                         # validation/
OUT = V / "submission"; OUT.mkdir(exist_ok=True)
ZIP = OUT / "MANDATE_E4.3.1_submission.zip"
MODEL_ZIP = OUT / "MANDATE_E4.3_injection_model.zip"
ROOT = "MANDATE_E4.3.1"
SKIP = re.compile(r"(\.llm\.env$|\.env$|__pycache__|\.pyc$|\.console\.pid$|\.meta\.json$|console\.log$|/demo/runs/|build\.log$)")

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
          "prototype/tests/*.py", "prototype/tests/*.sh", "prototype/eval/*.py", "prototype/eval/*.md", "prototype/docs/**/*", "prototype/workspace_samples/*", "prototype/workspace/.gitkeep", "prototype/e2e/workbench_e2e.py",
          "prototype/e2e/llm_live_driver.py", "prototype/config/injection_model/*.json", "prototype/config/injection_model/.gitignore",
          "ml/behaviour_model/*.py", "ml/behaviour_model/*.md", "ml/behaviour_model/*.ipynb", "ml/behaviour_model/agentdojo_sequences.jsonl",
          "ml/injection_detector/make_notebook.py", "ml/injection_detector/MANDATE_injection_detector.ipynb", "ml/injection_detector/README.md"]:
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
          "prototype/eval/runs/20261018T0510-*-h5eval-s96x-run*/summary.json", "prototype/eval/runs/20261018T1600-*-h5eval-s97x-run*/summary.json", "prototype/e2e/runs/*-workbench/*",
          "prototype/e2e/runs/20261018T*-e2e/*", "prototype/e2e/runs/*-llm-live/*",
          "prototype/e2e/runs/20261016T172125-e2e/*", "prototype/e2e/runs/20261016T182547-e2e/*", "prototype/e2e/runs/20261016T182817-e2e/*",
          "prototype/tests/runs/**/*", "prototype/console/tests/runs/**/*",
          "prototype/submission_assets/**/*"]:
    add(p)

files = sorted({f for f in files if not SKIP.search(f.as_posix())})
# built by concatenation so this file does not match its own patterns
secret = re.compile(b"-----" + b"BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----|" + b"sk-" + b"ant-|" + b"AK" + b"IA[0-9A-Z]{16}|" + b"gh" + b"p_[A-Za-z0-9]{30}|" + b"gs" + b"k_[A-Za-z0-9]{40}")
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
# --- separate model archive (verified against the frozen manifest before it is written)
mdir = P / "config" / "injection_model"
want = next(l.split()[0] for l in (P / "FROZEN_E43.sha256").read_text().splitlines() if l.endswith("*config/injection_model/model.onnx"))
mh = hashlib.sha256()
with open(mdir / "model.onnx", "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
        mh.update(b)
if mh.hexdigest() != want:
    sys.exit(f"model.onnx sha256 {mh.hexdigest()} != frozen {want}; model archive NOT written")
with zipfile.ZipFile(MODEL_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for n in ("model.onnx", "tokenizer.json", "tokenizer_config.json", "config.json", "provenance.json"):
        z.write(mdir / n, n)
    z.writestr("README.txt", (P / "MODEL_RESTORE.md").read_text(encoding="utf-8"))
mz = hashlib.sha256(MODEL_ZIP.read_bytes()).hexdigest()
(OUT / (MODEL_ZIP.name + ".sha256")).write_text(f"{mz}  {MODEL_ZIP.name}\n", newline="\n")
print(f"wrote {MODEL_ZIP} ({MODEL_ZIP.stat().st_size / 1e6:.1f} MB) sha256 {mz}; model.onnx {want}")
(OUT / (ZIP.name + ".sha256")).write_text(f"{h}  {ZIP.name}\n", newline="\n")
print(f"wrote {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB, {len(files)} files) sha256 {h}")
