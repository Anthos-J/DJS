# S3 cell-network configuration (AM11)

| File | Role |
|---|---|
| `compose.cell.yaml` | **Canonical** MANDATE execution-cell reference profile. Contains the reusable `x-mandate-cell-network` template and role labels. Deploy only through `harness/deploy_cells.sh`. |
| `compose.yaml` | **Regression fixture, do not deploy.** The original playbook topology (`internal: true` only). It must keep reproducing the S3-T3 failure. |
| `regression/compose.cell.typo.yaml` | Fixture: the canonical profile with a misspelled gateway-mode key. Docker accepts it; the gate must refuse it. |
| `regression/compose.cell.no-isolated.yaml` | Fixture: the canonical profile without the AM11 driver options. The gate must refuse it. |
| `compose.isolated.yaml` | Historical first R1 remediation, superseded. Kept because earlier runs reference it. |
| `.env` | Image digests (netshoot, python:3.12-slim) |

## AM11 invariant (enforced by `harness/cell_policy.py`)

**Which networks it applies to.** A network is a cell network if it carries the label `mandate.role=execution-cell`, or if any cell-netns-owner joins it. An owner is a service whose network namespace another service shares, whatever its labels say. Removing labels therefore cannot opt a cell out. All other networks are left unconstrained.

**Each cell network must:**
- use the `bridge` driver;
- set `internal: true`;
- set `com.docker.network.bridge.gateway_mode_ipv4` and `gateway_mode_ipv6` to `isolated`, with no other `driver_opts`;
- have IPv6 off;
- have no explicit IPAM gateway;
- not be `external`.

At runtime the checker also requires that the IPAM config has no gateway and that the host-side `br-<id>` bridge has no IPv4 address.

**Members of a cell network.** Exactly one cell-netns-owner (the sidecar) plus at least one `gateway`. Anything else is forbidden, including test fixtures. A missing gateway is also a violation, so the approved route cannot be "fixed away".

**Agents** must:
- use `network_mode: service:<owner>` and join no networks directly;
- set `cap_drop: [ALL]`, with no `cap_add` and no `privileged`;
- set `read_only: true`;
- set `no-new-privileges:true`.

**Roles.** Every service must carry `mandate.role`, one of `cell-netns-owner`, `agent`, `gateway`, `test-fixture`, `pep`, `tool-server` or `control-plane` (the last three are forbidden on cell networks like every non-gateway role). A container labelled `mandate.oneshot=true` may be exited with code 0 at runtime.

`deploy_cells.sh` exits as follows:

| Exit | Meaning |
|---|---|
| 3 | Static violation; refused before `up` |
| 4 | Runtime violation; deployed, then torn down |
| 2 | Checker or `up` error; torn down |

**Docker behaviour (Engine 29.8.2, `runs/*-prereq-gateway-mode/prereq.log`):**
- It rejects `isolated` on a non-internal network.
- It rejects unknown mode values.
- It **silently accepts a misspelled option key** and then gives the network a host-side gateway. Docker alone does not fail closed, which is why the checker exists.
