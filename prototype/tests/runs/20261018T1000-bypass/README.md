# Cell bypass test (18 Oct 2026, live stack, engine E4.2.1)

Can a compromised agent cell get data out without passing the checkpoint (PEP)? `tests/bypass_from_cell.sh`, run from inside both agent cells against real listeners.

| Route tried from the cell | Positive control (default Docker network) | Cell A / Cell B |
|---|---|---|
| Raw TCP to a real listener on the host (`host.docker.internal`, and the gateway IP 192.168.65.254) | connected | blocked |
| DNS lookup (`example.com`) | resolved | blocked |
| Raw UDP DNS query to 8.8.8.8 (DNS tunnelling channel) | answered | blocked |
| Internet TCP 1.1.1.1:443 | timed out (this host's own network) | blocked |
| Direct to the tool server, the PEP, or the control plane (skipping the checkpoint) | not applicable | blocked: names don't resolve and the networks aren't attached |
| Terminator 8443 without a client certificate | not applicable | reachable, refused (400) |

The host listener received 2 connections, both from the positive control and none from the cells. **RESULT=PASS.**

Limits:
- **Internet TCP:** the internet-TCP probe has no working positive control on this host, so that row shows the cell is blocked but not that the probe would otherwise succeed.
- **Terminator:** it is the one intended exit. It only accepts mTLS with the cell's own certificate, and that binding was validated separately (S7).
- **Scope:** this tests network routes out of the cell. A real tool server that exfiltrates data itself is outside what MANDATE controls.
