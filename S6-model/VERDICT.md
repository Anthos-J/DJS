# S6 Model-route enforcement (mitmproxy 12.2.3, reverse mode): verdict

**Runs:** `runs/20261016T001637-run3` and `runs/20261016T001821-run4`: **32 PASS, 1 BLOCKED (T9)** each.
- `run1` and `run2` were harness errors: the control container lacked the harness mount. Both have NOTE files.

**Status:** ledger 30 and 31 **LOCALLY REPRODUCED** against a **mock** provider. **Not SECURITY-TESTED.** T9 is **BLOCKED** pending your decision.
**Runner:** Claude. **Reviewer:** not assigned.

## Setup

- **Image:** `mandate-mitm:wave3` (`sha256:0ac91aba…`).
- **Topology** (AM11 static and runtime gate passed before every run):
  - `agent`: hardened; shares the netns of `cellside` on AM11 `cellnet_m`.
  - `model-proxy`: `mitmdump --mode reverse:http://mock-provider:9000`; the only gateway; on `cellnet_m` and `provnet` (internal). It alone holds the dummy provider key.
  - `mock-provider`: on `provnet`; logs every TCP accept and request (headers, body, SHA-256) **before** replying.
  - `outside`: on `provnet`; control.
- **Policy** (`harness/model_addon.py`), applied before any upstream contact:
  - Routes allowed: `POST /v1/messages`, `POST /v1/responses`.
  - Body must be UTF-8 JSON with identity encoding and an object at the top level. **Duplicate keys at any depth are rejected.**
  - Per-API top-level allowlist.
  - Anthropic tools: no `type`, or exactly `"custom"`. OpenAI tools: exactly `"function"`. A per-tool field allowlist applies to both.
  - The forwarded body is **re-serialized from the parsed object**, so the provider receives exactly what was checked.
  - Client credentials are dropped, and the proxy injects the provider key.

## Results (run3; run4 identical)

Judged at the mock provider's log. Every rejection has a paired positive control: the same request minus the offending element is forwarded.

| ID | Test | Result | Evidence |
|---|---|---|---|
| C-provider-observes-direct | `outside` → provider directly | **PASS** | request logged (the observer works) |
| T1 / T1b | Anthropic custom tools, without and with `type:"custom"` | **PASS** | 200; provider got `x-api-key: DUMMY-PROVIDER-KEY-4b9d` |
| T1c | Client sends `x-api-key: ATTACKER-KEY` and `Authorization: Bearer ATTACKER` | **PASS** | provider saw only the injected key; "ATTACKER" never reached it |
| T1d | Cell sends no key | **PASS** | provider still received the injected key; the cell holds none |
| T1e | Canonical forwarding | **PASS** | provider body == re-serialized checked object, not the client's raw bytes |
| T4-ctl | OpenAI `type:"function"` | **PASS** | forwarded with `Authorization: Bearer <injected>` |
| T2 / T2b / T2c | `web_search_20260209`; custom + web_search mixed; `code_execution_20250825` | **PASS** | 400 from the proxy; **provider received nothing** |
| T3 | `mcp_servers` | **PASS** | 400; nothing at the provider |
| T4 / T4b / T4c | OpenAI `web_search`, `mcp`, untyped tool | **PASS** | 400; nothing at the provider |
| T5 / T5b / T5c | Unknown tool type; unknown top-level field (`container`); unknown tool field (`server_url`) | **PASS** | 400; nothing at the provider |
| T6–T6j | Smuggling (10 cases): duplicate `tools`; duplicate nested `type`; `"Custom"` / `"Function"`; `tools` escaped key; `"tools "` with a space; tools as an object; top-level array; non-JSON body; other route | **PASS** (10/10) | each 400; nothing at the provider |
| T6k / T6l | gzip-encoded body (malicious / benign) | **PASS** | 400; no decompress-then-check differential |
| T7 | SSE | **PASS** | 5 events about 0.6 s apart |
| T8 / T8b | Cell → mock provider by name and IP; cell → `api.anthropic.com` / `api.openai.com` | **PASS** | name resolution fails / network unreachable; nothing at the provider (control C passes) |
| **T9** | Live provider smoke | **BLOCKED** | needs a decision; see below |

**Checked independently in the provider log (run3):**
- 8 requests in total: the 7 forwarded by the proxy, plus 1 keyless direct request from the control.
- Keys seen: the injected key ×7 (Anthropic ×6, OpenAI ×1), and none on the control request.
- **0 provider requests contain** `web_search`, `mcp_servers`, `code_execution`, `container`, `future_tool`, `server_url` or `ATTACKER`.
- The proxy log shows 22 rejects and 7 forwards.

## T9: what is needed from you before it can run

T9 is optional in the playbook (§8.2, not a gate blocker). It was **not attempted, and no provider response was fabricated**. To run it I need:

1. **The provider(s):** Anthropic Messages and/or OpenAI Responses.
2. **An API key** with a hard spending limit. It must be supplied to the `model-proxy` container only, as an environment variable or Docker secret that **you** set. I will not type it, and it must never be put in the cell.
3. **Explicit consent to send live requests:** about 3 requests, one allowed and two server-tool requests that must be blocked before reaching the provider.
4. **An egress path for the model proxy only:** a non-internal network attached to `model-proxy`, not to the cell. This changes the S6 topology for that one test.
5. **The pinned model ID** to use.

## Limitations

- **Mock provider only.** The real APIs' field sets evolve, so the allowlist needs maintenance. Provider-side retention is out of scope.
- The allowlists are a snapshot written for this spike. Unknown future fields are rejected, which is fail-closed.
- Response-side checks (e.g. provider-executed tool results in responses) were not tested.

## Reproduce

```
bash driver/run_s6.sh <label>
```
