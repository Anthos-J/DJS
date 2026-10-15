"""Build-time fetch of the Cedar CLI and cvc5 with SHA-256 verification (fails the build on mismatch).
Usage: fetch_tools.py <cedar_url> <cedar_sha256> <cvc5_url> <cvc5_sha256-or-empty> <dest>"""
import hashlib, io, json, os, stat, sys, tarfile, urllib.request, zipfile

cedar_url, cedar_sha, cvc5_url, cvc5_sha, dest = sys.argv[1:6]
os.makedirs(f"{dest}/bin", exist_ok=True)
manifest = {}

def fetch(url, want):
    data = urllib.request.urlopen(url, timeout=120).read()
    got = hashlib.sha256(data).hexdigest()
    manifest[url.rsplit("/", 1)[1]] = {"url": url, "bytes": len(data), "sha256": got, "expected": want or "none published"}
    if want and got != want:
        sys.exit(f"SHA-256 MISMATCH for {url}: got {got}, expected {want}")
    return data

with tarfile.open(fileobj=io.BytesIO(fetch(cedar_url, cedar_sha)), mode="r:xz") as t:
    m = [x for x in t.getmembers() if x.isfile() and x.name.rsplit("/", 1)[-1] == "cedar"]
    assert len(m) == 1, [x.name for x in t.getmembers()]
    open(f"{dest}/bin/cedar", "wb").write(t.extractfile(m[0]).read())
with zipfile.ZipFile(io.BytesIO(fetch(cvc5_url, cvc5_sha))) as z:
    m = [n for n in z.namelist() if n.endswith("/bin/cvc5")]
    assert len(m) == 1, z.namelist()[:20]
    open(f"{dest}/bin/cvc5", "wb").write(z.read(m[0]))
for b in ("cedar", "cvc5"):
    p = f"{dest}/bin/{b}"
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    manifest[f"bin/{b}"] = {"sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
json.dump(manifest, open(f"{dest}/tools_manifest.json", "w"), indent=1)
print(json.dumps(manifest, indent=1))
