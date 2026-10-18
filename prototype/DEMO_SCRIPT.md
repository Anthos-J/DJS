# MANDATE demonstration script (about 8–10 minutes)

Use the same terms as the PPT. Every claim below is backed by a live check in the console or a recorded evidence file. Do not claim more than this.

**Before judges arrive:**
1. Run `bash demo/launch.sh`.
2. Open http://127.0.0.1:8090 and confirm the header shows *control plane up*, *engine E4.3* and *audit chain OK*. In System health, *Injection detector* should read *loaded*.
3. Guided scenarios → **Reset demo** if anything was run earlier.

| # | Click | Judges should observe | Claim supported (and its limit) |
|---|---|---|---|
| 0 | **Home** | Live health, engine E4.3, two declared agents, empty queues | Status comes from the running control plane, not from the page |
| 1 | See it work → Guided scenarios → Run story **1** | PASS: both calls executed; the tool server shows exactly 2 effects | Normal in-role work is not blocked |
| 2 | Run story **2** | PASS: document read allowed; HR read **DENIED** with a valid credential; exfiltration **DENIED**; tool server saw only the read; agent **QUARANTINED** | The problem-statement attack is stopped at the PEP (scripted agent, mock tools) |
| 3 | Run story **3**, then **Operate → Decisions** → click the Blocked row | Risk score, factors with evidence, expected authority, stopping control | Explanations are real engine output. The score is ordinal, not a probability |
| 4 | Run story **4** | Owner resume recorded with a reason; work continues | Containment is reversible only by the owner, and audited |
| 5 | Run story **5**, then **Operate → Approvals** | Purchase held; approved once; first retry executes, second needs approval again; 1 effect | One-time approvals execute at most once |
| 6 | Run story **6** | Delegated read allowed; out-of-scope web search **DENIED**; child **QUARANTINED** | Delegation is attenuated |
| 7 | Run story **7** | Cold-start decisions labelled low-confidence; a declared task change is not drift | Legitimate change is supported |
| 8 | Run story **8**, then **Operate → Agents & mandates** → try *Assign* on an HR task with no subject | Server refuses an HR task without scope (400); subject read OK; mail to a colleague named in the instruction **DENIED**; mail service received 0 mails | Names in free text never authorize HR access |
| 9 | Run story **9** | Wiki write after a web read **held**; tool server shows no write | Poisoned content does not enter the trusted store without approval (60 legitimate research writes also need approval: a trade-off) |
| 10 | Run story **10** | Agent B quarantined → control plane restarted → still quarantined; call denied, no effect | Security state survives restarts |
| 11 | Run story **11**, then **Proof → Recovery** → *Start in owner recovery mode* → *Acknowledge* | Control plane **refuses to start**; PEP denies; recovery mode needs approvals until you acknowledge | Missing history is not silently reset. Owner-accepted recovery forgets it (limitation V2) |
| 12 | Guided scenarios → **Reset demo**, then Run **12** | Control plane stopped → call denied "unreachable", no effect | Fail-closed |
| 13 | **Proof → Audit trail** | Verified hash chain; filter by `status_changed` or `approval_resolved` | Tamper-evident record of what the control plane saw. It does not prove anything about traffic outside the PEP |
| 14 | **Proof → Results** | Final E4.3 (seeds 961–965): 1,260 attack scenarios, **30 succeeded (C4)**; 840 legitimate, **0 denied, 124 needed approval**; identical to E4.2.1 on the same seeds. Below that, the detector's own test table | Engine-level, AI-generated scenarios. **Not a real-world prevention rate.** E4.3 = E4.2.1 there because the scenarios have no document text. The detector table describes the detector on public datasets, not attack success |
| 14b | **Proof → System health** | Injection detector: loaded, threshold 0.5, the five scanned document tools, and *Not scanned: structured records*. Sequence model: alert-only | The UI reports what the running control plane actually loaded |
| 15 | **See it work → Try an attack**: let a judge pick a preset or type an attack | Verdict, factors and stopping control; *SIMULATION: nothing executed*, live state unchanged | Judges can test their own ideas against the real engine safely |
| 16 | **Operate → Attack map** | Red paths for the denied HR read and exfiltration, a dashed delegation arc, the quarantined agent outlined | The whole incident at a glance, from real decisions |
| 17 | Operate → Decisions → Blocked row → **Export verifiable evidence pack** → run the offline verifier, edit the file, run it again | VERIFIED, then FAILED after the edit | Tamper-evident evidence an auditor can check without MANDATE (not signed) |

**Closing statement (keep it):**
> This is a working prototype, verified on one machine with scripted agents and mock tools. One attack family, below-budget reading (C4), still succeeds. E4.3 adds a prompt-injection detector we trained ourselves. It catches most injected documents in its own tests and misses about one in four from an unseen source, and it does not scan structured records. In a small live-LLM demonstration (15 runs) it flagged every injected document. Where the model followed an injection, its external e-mail was held, though our older rules would have held it too. It has not had independent human review or a second-machine reproduction. The full limitation register is in the console.
