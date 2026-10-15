"""Analyze S3 pcaps using the run's actual subnets. Usage: python analyze_pcap.py <run_dir>"""
import json, os, subprocess, sys
from pathlib import Path

R = Path(sys.argv[1]).resolve()
N = "nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70"
ctx = json.loads((R / "context.json").read_text())
nets = {}
for n in ["cellnet_a", "cellnet_b", "edge"]:
    j = json.loads((R / f"net_{n}.json").read_text())[0]
    cfg = j["IPAM"]["Config"][0]
    nets[n] = {"subnet": cfg["Subnet"], "gateway": cfg.get("Gateway", ""), "options": j.get("Options", {})}
win = subprocess.run(["cygpath", "-w", str(R / "pcap")], capture_output=True, text=True).stdout.strip() or str(R / "pcap")

def td(pcap, flt="", extra=""):
    cmd = f"tcpdump -nn -r /cap/{pcap} {('' if not flt else repr(flt))} 2>/dev/null {extra}"
    cp = subprocess.run(["docker", "run", "--rm", "-v", f"{win}:/cap", N, "sh", "-c", cmd],
                        capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    return cp.stdout

a, b = nets["cellnet_a"]["subnet"], nets["cellnet_b"]["subnet"]
out = {"nets": nets}
host_all = td("host_vm.pcap")
out["host_vm_total"] = len(host_all.splitlines())
out["host_vm_cell_dns_probe"] = host_all.count(ctx["dns_probe_cell"])
out["host_vm_ctl_dns_probe"] = host_all.count(ctx["dns_probe_ctl"])
from_cells = td("host_vm.pcap", f"src net {a} or src net {b}")
out["host_vm_pkts_from_cellnets"] = len(from_cells.splitlines())
# destinations of cell-sourced packets seen in host netns
dsts = sorted({l.split(" > ")[1].split(":")[0].rsplit(".", 1)[0] for l in from_cells.splitlines() if " > " in l})
out["host_vm_cell_pkt_destinations"] = dsts
cell = td("cell_a.pcap", "ip")
out["cell_a_ip_packets"] = len(cell.splitlines())
offnet = td("cell_a.pcap", f"ip and not dst net {a} and not dst net 127.0.0.0/8")
out["cell_a_offsubnet_dst_packets"] = len(offnet.splitlines())
out["cell_a_offsubnet_sample"] = offnet.splitlines()[:5]
out["cell_a_ipv6_packets"] = len(td("cell_a.pcap", "ip6").splitlines())
(R / "pcap_analysis.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "nets"}, indent=1))
print("cellnet_a:", nets["cellnet_a"])
