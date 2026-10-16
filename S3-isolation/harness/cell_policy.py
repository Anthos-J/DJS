"""AM11 execution-cell network policy checker (fail closed).

Usage:
  python cell_policy.py static  <compose-file> [--env-file F] [--project P]   # resolved Compose model, before `up`
  python cell_policy.py static-json <resolved-config.json>                     # same rules on a saved/mutated model
  python cell_policy.py runtime <project> [--image NETSHOOT]                   # effective docker state, after `up`
Exit codes: 0 = compliant, 3 = policy violation, 2 = checker could not evaluate (callers must treat 2 as failure too).
Prints a JSON report {mode, compliant, violations[], facts}.

Roles come from the label `mandate.role` on every service: cell-netns-owner | agent | gateway | test-fixture.
Cell networks are those labelled mandate.role=execution-cell, PLUS any network a cell-netns-owner joins.
An owner on an unlabelled network is itself a violation, so omitting the label cannot opt a cell out.
"""
import json, os, subprocess, sys

ISO = "isolated"
GW4, GW6 = "com.docker.network.bridge.gateway_mode_ipv4", "com.docker.network.bridge.gateway_mode_ipv6"
ALLOWED_CELL_OPTS = {GW4, GW6}  # unknown keys are rejected: Docker silently accepts misspelled option keys
ROLES = {"cell-netns-owner", "agent", "gateway", "test-fixture", "pep", "tool-server", "control-plane"}  # pep / tool-server / control-plane: never on a cell network
NETSHOOT = "nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70"


class CheckerError(Exception):
    pass


def _run(cmd):
    cp = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    if cp.returncode != 0:
        raise CheckerError(f"{' '.join(cmd)} -> rc={cp.returncode}: {cp.stderr.strip()[:400]}")
    return cp.stdout


def _no_new_privs(opts):
    return any(o.replace("=", ":") in ("no-new-privileges:true", "no-new-privileges") for o in (opts or []))


# ------------------------------------------------------------------ static (Compose model)
def check_model(model):
    v, facts = [], {}
    nets, svcs = model.get("networks") or {}, model.get("services") or {}
    role = {s: ((d.get("labels") or {}).get("mandate.role")) for s, d in svcs.items()}
    for s, r in role.items():
        if r not in ROLES:
            v.append(f"service {s}: missing/unknown mandate.role label ({r!r})")
    # Structural detection: a service whose netns another service shares IS a cell owner, and the
    # sharer IS an agent, whatever their labels say. Labels cannot opt a cell out of the rules.
    shared = {s: d["network_mode"].split(":", 1)[1] for s, d in svcs.items()
              if (d.get("network_mode") or "").startswith("service:")}
    for s, tgt in shared.items():
        if role.get(tgt) != "cell-netns-owner":
            v.append(f"service {tgt}: shares its network namespace with {s} but is not labelled cell-netns-owner")
            role[tgt] = "cell-netns-owner"
        if role.get(s) != "agent":
            v.append(f"service {s}: uses network_mode service:{tgt} but is not labelled agent")
            role[s] = "agent"
    owners = [s for s, r in role.items() if r == "cell-netns-owner"]
    svc_nets = {s: list((d.get("networks") or {}).keys()) for s, d in svcs.items()}

    cell_nets = {n for n, d in nets.items() if ((d or {}).get("labels") or {}).get("mandate.role") == "execution-cell"}
    for o in owners:
        if not svc_nets[o]:
            v.append(f"owner {o}: joins no network")
        for n in svc_nets[o]:
            if n not in cell_nets:
                v.append(f"owner {o}: joins network {n} that is not labelled mandate.role=execution-cell")
                cell_nets.add(n)  # still hold it to the full AM11 rule set
        if len(svc_nets[o]) > 1:
            v.append(f"owner {o}: joins {len(svc_nets[o])} networks; a cell owner must join exactly one cell network")
        if svcs[o].get("network_mode"):
            v.append(f"owner {o}: must not set network_mode ({svcs[o]['network_mode']})")
    facts["cell_networks"] = sorted(cell_nets)
    facts["unconstrained_networks"] = sorted(set(nets) - cell_nets)

    for n in sorted(cell_nets):
        d = nets.get(n) or {}
        if d.get("external"):
            v.append(f"cell network {n}: external networks are not allowed (settings cannot be verified pre-deploy)")
        if (d.get("driver") or "bridge") != "bridge":
            v.append(f"cell network {n}: driver {d.get('driver')!r} != bridge")
        if d.get("internal") is not True:
            v.append(f"cell network {n}: internal is not true")
        if d.get("enable_ipv6") is True:
            v.append(f"cell network {n}: enable_ipv6 true (IPv6 cells are outside the validated profile)")
        opts = d.get("driver_opts") or {}
        for k in (GW4, GW6):
            if opts.get(k) != ISO:
                v.append(f"cell network {n}: {k} = {opts.get(k)!r}, required {ISO!r}")
        for k in set(opts) - ALLOWED_CELL_OPTS:
            v.append(f"cell network {n}: unexpected driver_opt {k!r}")
        for c in (d.get("ipam") or {}).get("config") or []:
            if c.get("gateway"):
                v.append(f"cell network {n}: explicit IPAM gateway {c['gateway']} is not allowed")
        members = [s for s, ns in svc_nets.items() if n in ns]
        mo = [s for s in members if role.get(s) == "cell-netns-owner"]
        mg = [s for s in members if role.get(s) == "gateway"]
        other = [s for s in members if s not in mo and s not in mg]
        if len(mo) != 1:
            v.append(f"cell network {n}: has {len(mo)} cell netns owners {mo}, required exactly 1")
        if not mg:
            v.append(f"cell network {n}: no gateway member (the approved route would be broken)")
        if other:
            v.append(f"cell network {n}: forbidden members {other} (only the cell sidecar and gateway allowed)")

    for s, r in role.items():
        d = svcs[s]
        if r != "agent":
            continue
        nm = d.get("network_mode") or ""
        tgt = nm.split(":", 1)[1] if nm.startswith("service:") else None
        if tgt not in owners:
            v.append(f"agent {s}: network_mode {nm!r} must be service:<cell-netns-owner>")
        if d.get("networks"):
            v.append(f"agent {s}: must not join networks directly")
        if "ALL" not in [c.upper() for c in d.get("cap_drop") or []]:
            v.append(f"agent {s}: cap_drop must include ALL")
        if d.get("cap_add"):
            v.append(f"agent {s}: cap_add not allowed ({d['cap_add']})")
        if d.get("privileged"):
            v.append(f"agent {s}: privileged not allowed")
        if d.get("read_only") is not True:
            v.append(f"agent {s}: read_only must be true")
        if not _no_new_privs(d.get("security_opt")):
            v.append(f"agent {s}: security_opt must include no-new-privileges:true")
    return v, facts


def static(compose, env_file=None, project=None):
    cmd = ["docker", "compose"] + (["-p", project] if project else []) + ["-f", compose]
    cmd += (["--env-file", env_file] if env_file else []) + ["config", "--format", "json"]
    return check_model(json.loads(_run(cmd)))


# ------------------------------------------------------------------ runtime (effective docker state)
def runtime(project, image=NETSHOOT):
    v, facts = [], {"networks": {}}
    ids = _run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"]).split()
    if not ids:
        raise CheckerError(f"no containers for project {project}")
    conts = json.loads(_run(["docker", "inspect"] + ids))
    by_id = {c["Id"]: c for c in conts}
    svc = lambda c: c["Config"]["Labels"].get("com.docker.compose.service")
    roles = {c["Id"]: c["Config"]["Labels"].get("mandate.role") for c in conts}
    role = lambda c: roles[c["Id"]]
    for c in conts:  # structural detection, as in check_model
        nm = c["HostConfig"].get("NetworkMode", "")
        if nm.startswith("container:"):
            tgt = nm.split(":", 1)[1]
            if roles.get(tgt) != "cell-netns-owner" and tgt in by_id:
                v.append(f"container {by_id[tgt]['Name']}: shares its netns with {c['Name']} but is not labelled cell-netns-owner")
                roles[tgt] = "cell-netns-owner"
            if roles[c["Id"]] != "agent":
                v.append(f"container {c['Name']}: uses NetworkMode container:... but is not labelled agent")
                roles[c["Id"]] = "agent"
    for c in conts:
        oneshot_ok = (c["Config"]["Labels"].get("mandate.oneshot") == "true" and c["State"]["Status"] == "exited"
                      and c["State"].get("ExitCode") == 0)
        if c["State"]["Status"] != "running" and not oneshot_ok:
            v.append(f"container {c['Name']}: state {c['State']['Status']} (exit {c['State'].get('ExitCode')})")
        if role(c) not in ROLES:
            v.append(f"container {c['Name']}: missing/unknown mandate.role label ({role(c)!r})")
    net_ids = _run(["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"]).split()
    nets = json.loads(_run(["docker", "network", "inspect"] + net_ids)) if net_ids else []
    labelled = {n["Name"] for n in nets if (n.get("Labels") or {}).get("mandate.role") == "execution-cell"}
    owners = [c for c in conts if role(c) == "cell-netns-owner"]
    cell_names = set(labelled)
    for o in owners:
        on = list((o["NetworkSettings"]["Networks"] or {}).keys())
        for n in on:
            if n not in labelled:
                v.append(f"owner {o['Name']}: attached to {n}, which is not labelled execution-cell")
                cell_names.add(n)
        if len(on) != 1:
            v.append(f"owner {o['Name']}: attached to {len(on)} networks {on}, required exactly 1 cell network")
    by_name = {n["Name"]: n for n in nets}
    missing = cell_names - set(by_name)
    if missing:
        nets += json.loads(_run(["docker", "network", "inspect"] + sorted(missing)))
        by_name = {n["Name"]: n for n in nets}
    host_addrs = _run(["docker", "run", "--rm", "--net", "host", image, "ip", "-o", "-4", "addr"])
    facts["host_vm_ipv4_addrs"] = host_addrs.splitlines()
    for name in sorted(cell_names):
        n = by_name[name]
        o = n.get("Options") or {}
        ipam = (n.get("IPAM") or {}).get("Config") or []
        br = o.get("com.docker.network.bridge.name") or f"br-{n['Id'][:12]}"
        members = [by_id[cid] for cid in (n.get("Containers") or {}) if cid in by_id]
        stray = [cid for cid in (n.get("Containers") or {}) if cid not in by_id]
        f = facts["networks"][name] = {
            "id": n["Id"], "driver": n["Driver"], "internal": n["Internal"], "enable_ipv6": n["EnableIPv6"],
            "options": o, "ipam": ipam, "host_bridge": br,
            "host_bridge_ipv4": [l for l in host_addrs.splitlines() if f" {br} " in f" {l} " or l.split()[1:2] == [br]],
            "members": sorted(f"{svc(c)}({role(c)})" for c in members)}
        if n["Driver"] != "bridge":
            v.append(f"{name}: driver {n['Driver']} != bridge")
        if n["Internal"] is not True:
            v.append(f"{name}: Internal is not true")
        if n["EnableIPv6"]:
            v.append(f"{name}: EnableIPv6 is true")
        for k in (GW4, GW6):
            if o.get(k) != ISO:
                v.append(f"{name}: effective {k} = {o.get(k)!r}, required {ISO!r}")
        for k in set(o) - ALLOWED_CELL_OPTS - {"com.docker.network.enable_ipv4", "com.docker.network.enable_ipv6"}:
            v.append(f"{name}: unexpected effective option {k!r}")
        if any(c.get("Gateway") for c in ipam):
            v.append(f"{name}: IPAM has a host-side gateway address {[c.get('Gateway') for c in ipam]}")
        if f["host_bridge_ipv4"]:
            v.append(f"{name}: host-side bridge {br} carries IPv4 {f['host_bridge_ipv4']}")
        if stray:
            v.append(f"{name}: members from outside the project {stray}")
        mo = [c for c in members if role(c) == "cell-netns-owner"]
        mg = [c for c in members if role(c) == "gateway"]
        other = [c["Name"] for c in members if c not in mo and c not in mg]
        if len(mo) != 1:
            v.append(f"{name}: {len(mo)} cell netns owners attached, required exactly 1")
        if not mg:
            v.append(f"{name}: no gateway attached (approved route broken)")
        if other:
            v.append(f"{name}: forbidden members {other}")
    owner_ids = {o["Id"] for o in owners}
    for c in conts:
        if role(c) != "agent":
            continue
        hc = c["HostConfig"]
        nm = hc.get("NetworkMode", "")
        if not (nm.startswith("container:") and nm.split(":", 1)[1] in owner_ids):
            v.append(f"agent {c['Name']}: NetworkMode {nm!r} is not container:<cell owner>")
        if "ALL" not in [x.upper() for x in hc.get("CapDrop") or []]:
            v.append(f"agent {c['Name']}: CapDrop lacks ALL")
        if hc.get("CapAdd"):
            v.append(f"agent {c['Name']}: CapAdd {hc['CapAdd']}")
        if hc.get("Privileged"):
            v.append(f"agent {c['Name']}: Privileged")
        if not hc.get("ReadonlyRootfs"):
            v.append(f"agent {c['Name']}: ReadonlyRootfs false")
        if not _no_new_privs(hc.get("SecurityOpt")):
            v.append(f"agent {c['Name']}: SecurityOpt lacks no-new-privileges")
    if not [c for c in conts if role(c) == "agent"]:
        v.append("no agent containers found (nothing was confined)")
    facts["cell_networks"] = sorted(cell_names)
    return v, facts


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    opt = lambda k: argv[argv.index(k) + 1] if k in argv else None
    try:
        if mode == "static":
            v, facts = static(argv[2], opt("--env-file"), opt("--project"))
        elif mode == "static-json":
            v, facts = check_model(json.loads(open(argv[2], encoding="utf-8").read()))
        elif mode == "runtime":
            v, facts = runtime(argv[2], opt("--image") or NETSHOOT)
        else:
            print(__doc__); return 2
    except (CheckerError, KeyError, IndexError, ValueError) as e:
        print(json.dumps({"mode": mode, "compliant": False, "checker_error": str(e)}, indent=1))
        return 2
    print(json.dumps({"mode": mode, "compliant": not v, "violations": v, "facts": facts}, indent=1))
    return 0 if not v else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
