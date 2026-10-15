"""S7 one-shot PKI + token issuer (test values only; generated fresh per run, never committed).
Writes each component's secrets ONLY into that component's volume:
  /vol/side_a  cell A sidecar: cell.crt/cell.key = cert A, auth.conf = JWT_A, ca.crt
  /vol/side_b  cell B sidecar: cert B, JWT_B
  /vol/side_c  cell C sidecar: cert B + JWT_A   (S7-T2: JWT_A placed in a sidecar holding cert B)
  /vol/term    terminator: server.crt/server.key (SAN terminator), ca.crt
  /vol/pep     PEP: issuer public key, revoked session list, ca.crt
  /vol/harness test fixture: certs, keys and negative-test tokens
Public evidence (thumbprints, claims, no private keys) -> /out/pki_public.json"""
import base64, datetime as dt, hashlib, json, os, sys
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

V, OUT = "/vol", sys.argv[1] if len(sys.argv) > 1 else "/out"
now = dt.datetime.now(dt.timezone.utc)
ISS, AUD = "mandate-gw", "mandate-pep"

def key():
    return ec.generate_private_key(ec.SECP256R1())

def pem_key(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

def pem_cert(c):
    return c.public_bytes(serialization.Encoding.PEM)

def name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

def cert(subject_key, cn, issuer_key, issuer_name, *, ca=False, server_dns=None, client=False, days=2):
    b = (x509.CertificateBuilder().subject_name(name(cn)).issuer_name(issuer_name)
         .public_key(subject_key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if server_dns:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(server_dns)]), critical=False)
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    if client:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
    return b.sign(issuer_key, hashes.SHA256())

def x5t(c):  # RFC 8705 cnf.x5t#S256 = base64url(SHA-256(DER(cert))), no padding
    return base64.urlsafe_b64encode(hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).digest()).rstrip(b"=").decode()

ca_k = key(); ca = cert(ca_k, "mandate-test-ca", ca_k, name("mandate-test-ca"), ca=True)
srv_k = key(); srv = cert(srv_k, "terminator", ca_k, ca.subject, server_dns="terminator")
a_k = key(); a = cert(a_k, "cell-a", ca_k, ca.subject, client=True)
b_k = key(); b = cert(b_k, "cell-b", ca_k, ca.subject, client=True)
iss_k = key(); rogue_iss_k = key()

def tok(sub, sid, thumb, *, exp_s=7200, k=iss_k, aud=AUD, iss=ISS, cnf=True, alg="ES256"):
    claims = {"iss": iss, "aud": aud, "sub": sub, "sid": sid, "iat": int(now.timestamp()), "exp": int(now.timestamp()) + exp_s}
    if cnf:
        claims["cnf"] = {"x5t#S256": thumb}
    return jwt.encode(claims, k, algorithm=alg)

T = {
    "JWT_A": tok("agent:cell-a", "sess-A-1", x5t(a)),
    "JWT_B": tok("agent:cell-b", "sess-B-1", x5t(b)),
    "JWT_A_expired": tok("agent:cell-a", "sess-A-2", x5t(a), exp_s=-60),
    "JWT_A_revoked": tok("agent:cell-a", "sess-A-revoked", x5t(a)),
    "JWT_A_rogue_issuer": tok("agent:cell-a", "sess-A-3", x5t(a), k=rogue_iss_k),
    "JWT_A_wrong_aud": tok("agent:cell-a", "sess-A-4", x5t(a), aud="some-other-service"),
    "JWT_A_no_cnf": tok("agent:cell-a", "sess-A-5", x5t(a), cnf=False),
}
h, p, s = T["JWT_A"].split(".")
claims = json.loads(base64.urlsafe_b64decode(p + "=="))
claims["sub"] = "agent:cell-b"  # tampered payload, original signature
T["JWT_A_tampered"] = h + "." + base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode() + "." + s
none_h = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
T["JWT_A_alg_none"] = none_h + "." + p + "."

def w(path, data, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    os.chmod(path, mode)

def auth_conf(t):
    return f'proxy_set_header Authorization "Bearer {t}";\n'

for comp, (c, k, t) in {"side_a": (a, a_k, "JWT_A"), "side_b": (b, b_k, "JWT_B"), "side_c": (b, b_k, "JWT_A")}.items():
    w(f"{V}/{comp}/cell.crt", pem_cert(c), 0o644); w(f"{V}/{comp}/cell.key", pem_key(k))
    w(f"{V}/{comp}/auth.conf", auth_conf(T[t])); w(f"{V}/{comp}/ca.crt", pem_cert(ca), 0o644)
w(f"{V}/term/server.crt", pem_cert(srv), 0o644); w(f"{V}/term/server.key", pem_key(srv_k)); w(f"{V}/term/ca.crt", pem_cert(ca), 0o644)
w(f"{V}/pep/issuer_pub.pem", iss_k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), 0o644)
w(f"{V}/pep/revoked.txt", "sess-A-revoked\n", 0o644); w(f"{V}/pep/ca.crt", pem_cert(ca), 0o644)
for n, c in {"a": a, "b": b, "ca": ca}.items():
    w(f"{V}/harness/{n}.crt", pem_cert(c), 0o644)
w(f"{V}/harness/a.key", pem_key(a_k)); w(f"{V}/harness/b.key", pem_key(b_k))
rogue_k = key(); rogue = cert(rogue_k, "cell-a", rogue_k, name("rogue-ca"), client=True)  # self-signed, same CN as cell A
w(f"{V}/harness/rogue.crt", pem_cert(rogue), 0o644); w(f"{V}/harness/rogue.key", pem_key(rogue_k))
w(f"{V}/harness/tokens.json", json.dumps(T, indent=1))

pub = {"x5t#S256": {"cell-a": x5t(a), "cell-b": x5t(b), "rogue": x5t(rogue)},
       "tokens": {n: {"header": jwt.get_unverified_header(t) if n != "JWT_A_alg_none" else {"alg": "none"},
                      "claims": json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "==")), "prefix": t[:12]} for n, t in T.items()},
       "placement": {"side_a": "cert A + JWT_A", "side_b": "cert B + JWT_B", "side_c": "cert B + JWT_A", "agents": "nothing"}}
os.makedirs(OUT, exist_ok=True)
w(f"{OUT}/pki_public.json", json.dumps(pub, indent=1), 0o644)
print(json.dumps(pub["x5t#S256"]))
