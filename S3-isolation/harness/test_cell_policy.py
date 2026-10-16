"""Mutation tests for the AM11 static checker. Usage: python test_cell_policy.py <out_dir>
Resolves the canonical compose.cell.yaml once, applies one mutation per case, and asserts that the checker
reports a violation matching the expected text (control case: unmutated model must be compliant)."""
import copy, json, subprocess, sys
from pathlib import Path

H = Path(__file__).resolve().parent
sys.path.insert(0, str(H))
import cell_policy as cp  # noqa: E402

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CFG = H.parent / "config"
base = json.loads(subprocess.run(["docker", "compose", "-p", "s3iso", "-f", str(CFG / "compose.cell.yaml"),
                                  "--env-file", str(CFG / ".env"), "config", "--format", "json"],
                                 capture_output=True, text=True, check=True).stdout)
(OUT / "canonical_resolved.json").write_text(json.dumps(base, indent=1))
GW4, GW6 = cp.GW4, cp.GW6

def m(fn):
    d = copy.deepcopy(base); fn(d); return d
def setp(d, path, val):
    for k in path[:-1]: d = d[k]
    d[path[-1]] = val
def delp(d, path):
    for k in path[:-1]: d = d[k]
    del d[path[-1]]

CASES = [
    ("control-canonical", lambda d: None, None),
    ("drop-gateway_mode_ipv4", lambda d: delp(d, ["networks", "cellnet_a", "driver_opts", GW4]), "gateway_mode_ipv4 = None"),
    ("drop-gateway_mode_ipv6", lambda d: delp(d, ["networks", "cellnet_b", "driver_opts", GW6]), "gateway_mode_ipv6 = None"),
    ("drop-all-driver_opts", lambda d: delp(d, ["networks", "cellnet_a", "driver_opts"]), "gateway_mode_ipv4 = None"),
    ("ipv4-mode-nat", lambda d: setp(d, ["networks", "cellnet_a", "driver_opts", GW4], "nat"), "gateway_mode_ipv4 = 'nat'"),
    ("misspelled-key (Docker accepts this silently)",
     lambda d: (delp(d, ["networks", "cellnet_a", "driver_opts", GW4]),
                setp(d, ["networks", "cellnet_a", "driver_opts", "com.docker.network.bridge.gatway_mode_ipv4"], "isolated")),
     "unexpected driver_opt"),
    ("internal-false", lambda d: setp(d, ["networks", "cellnet_a", "internal"], False), "internal is not true"),
    ("internal-missing", lambda d: delp(d, ["networks", "cellnet_b", "internal"]), "internal is not true"),
    ("enable_ipv6-true", lambda d: setp(d, ["networks", "cellnet_a", "enable_ipv6"], True), "enable_ipv6 true"),
    ("driver-not-bridge", lambda d: setp(d, ["networks", "cellnet_a", "driver"], "macvlan"), "!= bridge"),
    ("external-cell-network", lambda d: setp(d, ["networks", "cellnet_b", "external"], True), "external networks are not allowed"),
    ("explicit-ipam-gateway", lambda d: setp(d, ["networks", "cellnet_a", "ipam"], {"config": [{"subnet": "10.99.0.0/24", "gateway": "10.99.0.1"}]}), "explicit IPAM gateway"),
    ("cell-label-removed (opt-out attempt)", lambda d: delp(d, ["networks", "cellnet_a", "labels"]), "not labelled mandate.role=execution-cell"),
    ("role-labels-removed (opt-out attempt)",
     lambda d: (delp(d, ["services", "sidecar_a", "labels"]), delp(d, ["services", "agent_a", "labels"])),
     "shares its network namespace with agent_a"),
    ("extra-member-on-cell-network", lambda d: setp(d, ["services", "outside", "networks"], {"edge": None, "cellnet_a": None}), "forbidden members ['outside']"),
    ("gateway-removed-from-cell (breaks approved route)", lambda d: delp(d, ["services", "gateway", "networks", "cellnet_a"]), "no gateway member"),
    ("sidecar-also-on-edge", lambda d: setp(d, ["services", "sidecar_a", "networks"], {"cellnet_a": None, "edge": None}), "joins network edge"),
    ("agent-joins-network-directly",
     lambda d: (delp(d, ["services", "agent_a", "network_mode"]), setp(d, ["services", "agent_a", "networks"], {"cellnet_a": None})),
     "must be service:<cell-netns-owner>"),
    ("agent-cap_drop-removed", lambda d: delp(d, ["services", "agent_a", "cap_drop"]), "cap_drop must include ALL"),
    ("agent-cap_add-NET_RAW", lambda d: setp(d, ["services", "agent_b", "cap_add"], ["NET_RAW"]), "cap_add not allowed"),
    ("agent-not-read_only", lambda d: setp(d, ["services", "agent_a", "read_only"], False), "read_only must be true"),
    ("agent-no-new-privileges-removed", lambda d: delp(d, ["services", "agent_a", "security_opt"]), "no-new-privileges"),
    ("agent-privileged", lambda d: setp(d, ["services", "agent_b", "privileged"], True), "privileged not allowed"),
    ("unlabelled-extra-service", lambda d: setp(d, ["services", "stray"], {"image": "x", "networks": {"edge": None}}), "service stray: missing/unknown"),
    ("control-plane-on-cell-network (added with the prototype)",
     lambda d: setp(d, ["services", "ctl"], {"image": "x", "labels": {"mandate.role": "control-plane"}, "networks": {"cellnet_a": None}}), "forbidden members ['ctl']"),
]

rows, ok = [], True
for name, fn, expect in CASES:
    v, facts = cp.check_model(m(fn))
    if expect is None:
        passed = not v
    else:
        passed = any(expect in x for x in v)
    ok &= passed
    rows.append({"case": name, "expected": expect or "compliant", "violations": v, "result": "PASS" if passed else "FAIL"})
    print(f"{'PASS' if passed else 'FAIL'}  {name:52s} {len(v)} violation(s)")
(OUT / "checker_mutation_results.json").write_text(json.dumps(rows, indent=1))
print(f"MUTATION SUMMARY: {sum(r['result'] == 'PASS' for r in rows)}/{len(rows)} PASS")
sys.exit(0 if ok else 1)
