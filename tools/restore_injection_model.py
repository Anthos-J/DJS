"""Restore the E4.3 injection-detector model (model.onnx, ~568 MB, not in git) from a model archive.

Accepted archives: the release model archive (MANDATE_E4.3_injection_model.zip) or the owner's original Colab output
(mandate_injection_detector*.zip). Both contain model.onnx at the top level.

The expected sha256 is read from prototype/FROZEN_E43.sha256 (the frozen engine manifest), never from the archive.
model.onnx is hashed while it is extracted to a temporary file and is only moved into place if the hash matches;
on any mismatch nothing is installed and the exit code is 2. E4.3's launcher refuses to start without a matching model.

Usage: python tools/restore_injection_model.py <archive.zip> [--check]
       --check   verify an already-installed model only (no archive needed: pass - as the archive)"""
import hashlib, os, sys, tempfile, zipfile
from pathlib import Path

V = Path(__file__).resolve().parent.parent                       # validation/
DST = V / "prototype" / "config" / "injection_model"
FILES = ("model.onnx", "tokenizer.json", "tokenizer_config.json", "config.json", "provenance.json")


def expected():
    for line in (V / "prototype" / "FROZEN_E43.sha256").read_text(encoding="utf-8").splitlines():
        h, _, name = line.strip().partition(" *")
        if name == "config/injection_model/model.onnx":
            return h
    sys.exit("FROZEN_E43.sha256 has no entry for config/injection_model/model.onnx")


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    want = expected()
    if "--check" in sys.argv:
        p = DST / "model.onnx"
        have = sha_file(p) if p.exists() else None
        print(f"expected {want}\ninstalled {have or 'MISSING'}")
        sys.exit(0 if have == want else 2)
    z = zipfile.ZipFile(sys.argv[1])
    names = set(z.namelist())
    missing = [f for f in FILES if f not in names]
    if missing:
        sys.exit(f"archive lacks {missing}")
    DST.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DST, prefix=".model-", suffix=".part"); os.close(fd)
    h = hashlib.sha256()
    try:
        with z.open("model.onnx") as src, open(tmp, "wb") as out:
            for b in iter(lambda: src.read(1 << 20), b""):
                h.update(b); out.write(b)
        if h.hexdigest() != want:
            print(f"REFUSED: model.onnx sha256 {h.hexdigest()} != frozen {want}; nothing installed"); sys.exit(2)
        for f in FILES[1:]:
            (DST / f).write_bytes(z.read(f))
        os.replace(tmp, DST / "model.onnx")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"OK: model.onnx installed and verified (sha256 {want})")


if __name__ == "__main__":
    main()
