#!/usr/bin/env bash
# Release R-E4.3 package check from a CLEAN extraction (same machine; not a clean-machine test).
#   1 ZIP checksums match their .sha256 files    2 every file matches MANIFEST.sha256    3 no secrets / no model inside the code ZIP
#   4 E4.3 refuses to start without the model (exit 5)   5 restore refuses a corrupted archive (exit 2, nothing installed)
#   6 restore installs and verifies the real model     7 launch from the extracted tree: E4.3, detector loaded, E2E 17/17
# Usage: bash tests/zip_clean_extraction_check.sh <submission_dir> <out_dir>
set -u
SUB="$(cygpath -m "$1")"; OUT="$(cygpath -m "$2")"; mkdir -p "$OUT"; LOG="$OUT/check.log"; : > "$LOG"
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
log() { echo "$*" | tee -a "$LOG"; }
X="$(cygpath -m "$(mktemp -d)")"; log "clean extraction dir: $X"
cd "$SUB" || { log "cannot cd to $SUB"; exit 1; }
SZ="${SUBMISSION_ZIP:-MANDATE_E4.3.1_submission.zip}"; SR="${SZ%_submission.zip}"
for z in "$SZ" MANDATE_E4.3_injection_model.zip; do
  if sha256sum -c "$z.sha256" >/dev/null 2>&1; then log "1 checksum OK  $z"; else log "1 checksum FAIL $z"; fi
done
python -I -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$SZ" "$X"
R="$X/$SR"
( cd "$R" && sha256sum -c MANIFEST.sha256 --quiet >/dev/null 2>&1 ) && log "2 MANIFEST.sha256: all files match ($(wc -l < "$R/MANIFEST.sha256") entries)" || log "2 MANIFEST.sha256: MISMATCH"
python -I - "$SUB/$SZ" <<'PY' | tee -a "$LOG"
import os, re, sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); names = z.namelist()
key = os.environ.get("GROQ_API_KEY", "")
pat = re.compile(rb"gsk_[A-Za-z0-9]{20,}|-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----")
hits = [n for n in names if pat.search(z.read(n)) or (key and key.encode() in z.read(n))]
print("3 secrets scan:", "none found" if not hits else hits, "| model.onnx inside code ZIP:", any(n.endswith("model.onnx") for n in names),
      "| .env/.llm.env files:", [n for n in names if n.endswith((".env", ".llm.env"))])
PY
cd "$R/prototype" || { log "ABORT: extraction missing at $R"; exit 1; }
log "working in extracted tree: $(pwd)"
export SPIKE_IMAGE=mandate-spike-py312:wave2 NGINX_IMAGE=nginx@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
MANDATE_ENGINE=E4.3.1 bash run_prototype.sh e2e > "$OUT/no_model_launch.txt" 2>&1; rc=$?
log "4 launch E4.3 without model: exit $rc ($(grep -o 'REFUSED[^.]*' "$OUT/no_model_launch.txt" | head -1))"
python -I - "$SUB/MANDATE_E4.3_injection_model.zip" "$OUT/corrupt.zip" <<'PY'
import sys, zipfile
src = zipfile.ZipFile(sys.argv[1]); dst = zipfile.ZipFile(sys.argv[2], "w")
for n in src.namelist():
    b = src.read(n)
    if n == "model.onnx":
        b = b[:-1] + bytes([b[-1] ^ 1])          # flip one bit in the last byte
    dst.writestr(n, b)
dst.close()
PY
python -I ../tools/restore_injection_model.py "$OUT/corrupt.zip" > "$OUT/restore_corrupt.txt" 2>&1; rc=$?
log "5 restore corrupted archive: exit $rc, installed=$( [ -f config/injection_model/model.onnx ] && echo yes || echo no ) ($(head -c 90 "$OUT/restore_corrupt.txt"))"
rm -f "$OUT/corrupt.zip"
python -I ../tools/restore_injection_model.py "$SUB/MANDATE_E4.3_injection_model.zip" > "$OUT/restore.txt" 2>&1; rc=$?
log "6 restore real archive: exit $rc ($(cat "$OUT/restore.txt"))"
python -I ../tools/restore_injection_model.py - --check >> "$OUT/restore.txt" 2>&1 && log "6 --check: installed model matches the frozen hash"
MANDATE_ENGINE=E4.3.1 bash run_prototype.sh e2e > "$OUT/e2e_from_zip.txt" 2>&1
log "7 $(grep -E 'injection_detector_enabled|SUMMARY' "$OUT/e2e_from_zip.txt" | tr '\n' ' ')"
cp -r "$(grep -o 'RUN=.*' "$OUT/e2e_from_zip.txt" | cut -d= -f2)" "$OUT/e2e_run_from_zip" 2>/dev/null
docker compose -f compose.yaml down -v --remove-orphans >/dev/null 2>&1
log "extraction left at $X (temporary)"
