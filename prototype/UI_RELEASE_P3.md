# UI release P3: product redesign of the MANDATE console

This release is presentation only. The engine, control-plane API, enforcement behaviour, console endpoints, evaluation evidence and disclosures are unchanged: `mandate/*`, `config/*`, `control/server.py` and `compose.yaml` match `FROZEN_UI_P2.sha256`. Freeze of this release: `FROZEN_UI_P3.sha256`.

## Design decisions

- **Identity: "the permission layer for AI agents."** The core metaphor is a *checkpoint*. Every agent action is stopped at a gate, checked against the agent's *mandate*, and stamped **Allowed**, **Held for you** or **Blocked**. The stamp is the product's signature visual.
- **Visual language: "registry, not war room."** Warm paper-and-ink palette, editorial serif headlines (Iowan Old Style / Palatino), a clean sans for the interface, and monospace only for evidence. A dark theme designed separately, plus a ◐ toggle. No external fonts or libraries: it works offline.
- **Information architecture.** Nine technical tabs became four plain-language areas:
  - **Home** (what, how, why, live state);
  - **See it work** (guided scenarios, try an attack, live AI agent);
  - **Operate** (agents & mandates, approvals, decisions, attack map);
  - **Proof** (results, audit trail, known limits, recovery, system health).
- **Plain-language layer.** Engine decisions are rendered as sentences ("Procurement agent A tried to read HR records (all) → Blocked: that tool is not part of the agent's role at all"). The sentences are derived from the engine's own control codes and reasons, and unknown codes fall back to the engine's text, so nothing is invented. Raw records stay one click away ("Technical record", "raw record").
- **Self-explanation.** A 3-step "how it works" section, hover definitions for jargon (mandate, checkpoint, quarantine, held, risk score, audit trail, isolated cells, HR scope, drift, prompt injection), and story cards for every scenario stating *what happens*, *what to watch for* and *what it proves*.
- **Honesty kept visible.** Results state their denominators and that they are engine-level tests with AI-authored scenarios. C4's 30 successful attacks get a highlighted callout. Known limits are a first-class page. The footer on every page says "Not SECURITY-TESTED · not independently reviewed", and live, simulated and evaluated content are labelled separately.

## Defects found and fixed during the redesign (all in the new UI code)

- The timeline's "agent" step inherited agent-card styling (class collision). Renamed to `agentcard`.
- The risk bar rescaled its gradient to the filled width, so a score of 25 looked red. It now uses a fixed green-to-red scale.
- Approvals and audit lacked agent roles, so names showed as "Agent agent A". Roles are now looked up from `/api/agents`.
- The results table heading said "same test set", which is inaccurate because the final engine used fresh seeds. Corrected.
- The entrance animation replayed on every live refresh, causing flicker. It now plays only on navigation.
- System health showed the latest E2E run even when that was the default-engine regression. It now prefers the E4.2.1 submission run and labels the engine.
- The simulator phrased dry runs as if the agent had acted. It now says "If … tried to …, MANDATE would …".

## Verification

| Check | Result | Evidence |
|---|---|---|
| Console integration (21 live tests, including UI strings, simulator dry run and evidence-pack tamper detection) | 21/21 | `console/tests/runs/` (latest) |
| Every page rendered from live data in a browser; no console errors | yes | `submission_assets/screenshots/01–15` |
| Interactive: simulator preset → verdict; story 2 run from the UI → 5/5 checks verified; HR form, approvals and dialogs as in P1/P2 | yes | browser session |
| Narrow width (390 px) | no horizontal overflow (scroll width = viewport) | browser measurement |
