"""SymCC verdict parsing (AM10: the CLI exits 0 even when a property does NOT hold).
parse(rc, text) -> "HOLDS" | "DOES_NOT_HOLD" | "UNKNOWN". Fail closed: a CI gate passes only on "HOLDS".
HOLDS needs exit 0, exactly one VERIFIED verdict line, and no negative line. DOES_NOT_HOLD needs
exit 0, exactly one DOES NOT HOLD line, and a counterexample block. Anything else is UNKNOWN."""
import re

_OK = re.compile(r"^\s*✓ Policy set 1 implies policy set 2: VERIFIED\s*$")
_NO = re.compile(r"^\s*✗ Policy set 1 implies policy set 2: DOES NOT HOLD\s*$")


def parse(rc, text):
    lines = (text or "").splitlines()
    ok = [l for l in lines if _OK.match(l)]
    no = [l for l in lines if _NO.match(l)]
    if rc == 0 and len(ok) == 1 and not no:
        return "HOLDS"
    if rc == 0 and len(no) == 1 and not ok and "Counterexample found" in text:
        return "DOES_NOT_HOLD"
    return "UNKNOWN"


def gate(rc, text):
    """True only if the property is proven."""
    return parse(rc, text) == "HOLDS"
