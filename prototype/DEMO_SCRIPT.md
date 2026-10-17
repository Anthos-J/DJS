# MANDATE demonstration script (about 8–10 minutes)

Use the same terms as the PPT. Every claim below is backed by a live check in the console or a recorded evidence file. Do not claim more than this.

**Before judges arrive:**
1. Run `bash demo/launch.sh`.
2. Open http://127.0.0.1:8090 and confirm the header shows *control plane up*, *engine E4.2.1* and *audit chain OK*.
3. Live scenarios → **Reset demo** if anything was run earlier.

| # | Click | Judges should observe | Claim supported (and its limit) |
|---|---|---|---|
| 0 | **Overview** | Live health, engine E4.2.1, two declared agents, empty queues | Status comes from the running control plane, not from the page |
| 1 | Live scenarios → Run **1** | PASS: both calls executed; the tool server shows exactly 2 effects | Normal in-role work is not blocked |
| 2 | Run **2** | PASS: document read allowed; HR read **DENIED** with a valid credential; exfiltration **DENIED**; tool server saw only the read; agent **QUARANTINED** | The problem-statement attack is stopped at the PEP (scripted agent, mock tools) |
| 3 | Run **3**, then **Investigations** → click the DENY row | Risk score, factors with evidence, expected authority, stopping control | Explanations are real engine output. The score is ordinal, not a probability |
| 4 | Run **4** | Owner resume recorded with a reason; work continues | Containment is reversible only by the owner, and audited |
| 5 | Run **5**, then **Approvals** | Purchase held; approved once; first retry executes, second needs approval again; 1 effect | One-time approvals execute at most once |
| 6 | Run **6** | Delegated read allowed; out-of-scope web search **DENIED**; child **QUARANTINED** | Delegation is attenuated |
| 7 | Run **7** | Cold-start decisions labelled low-confidence; a declared task change is not drift | Legitimate change is supported |
| 8 | Run **8**, then **Agents & authority** → try *Assign* on an HR task with no subject | Server refuses an HR task without scope (400); subject read OK; mail to a colleague named in the instruction **DENIED**; mail service received 0 mails | Names in free text never authorize HR access |
| 9 | Run **9** | Wiki write after a web read **held**; tool server shows no write | Poisoned content does not enter the trusted store without approval (60 legitimate research writes also need approval: a trade-off) |
| 10 | Run **10** | Agent B quarantined → control plane restarted → still quarantined; call denied, no effect | Security state survives restarts |
| 11 | Run **11**, then **Recovery** → *Start in owner recovery mode* → *Acknowledge* | Control plane **refuses to start**; PEP denies; recovery mode needs approvals until you acknowledge | Missing history is not silently reset. Owner-accepted recovery forgets it (limitation V2) |
| 12 | Live scenarios → **Reset demo**, then Run **12** | Control plane stopped → call denied "unreachable", no effect | Fail-closed |
| 13 | **Audit explorer** | Verified hash chain; filter by `status_changed` or `approval_resolved` | Tamper-evident record of what the control plane saw. It does not prove anything about traffic outside the PEP |
| 14 | **Evaluation results** | Final E4.2.1: 1,260 attack scenarios, **30 succeeded (C4)**; 840 legitimate, **0 denied, 127 needed approval**; benign alert rate 0.094 | Engine-level, AI-generated scenarios. **Not a real-world prevention rate** |
| 15 | **Policy simulator**: let a judge pick a preset or type an attack | Verdict, factors and stopping control; *SIMULATION: nothing executed*, live state unchanged | Judges can test their own ideas against the real engine safely |
| 16 | **Attack graph** | Red paths for the denied HR read and exfiltration, a dashed delegation arc, the quarantined agent outlined | The whole incident at a glance, from real decisions |
| 17 | Investigations → DENY row → **Export verifiable evidence pack** → run the offline verifier, edit the file, run it again | VERIFIED, then FAILED after the edit | Tamper-evident evidence an auditor can check without MANDATE (not signed) |

**Closing statement (keep it):**
> This is a working prototype, verified on one machine with scripted agents and mock tools. One attack family, below-budget reading (C4), still succeeds. It has not had independent human review or a second-machine reproduction. The optional live-LLM agent was tried on three tasks: single runs, not rates. The full limitation register is in the console.
