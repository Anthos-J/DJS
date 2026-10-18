# Using "Your task": bring your own task to MANDATE

Start the demo, open http://127.0.0.1:8090 and click **Your task** (or **Bring your own task** on Home):

```bash
bash demo/launch.sh
```

## 1. Describe the task
Write what you want an AI agent to do, or click an example, for instance "Compare the supplier quotes, but do not access HR records". Your text becomes the owner's task instruction:
- Amounts and names in it count as your authorisation for those exact values. For example, "buy 40 valves from umbrella for 41.50" authorises 41.50.
- It can never add tools, data, destinations or HR scope.

## 2. Choose the agent and its job
| Agent | Jobs (the tools each job allows) |
|---|---|
| Procurement assistant | *Review supplier documents and prices* (your documents, supplier search, prices, purchase request); *Price check*; *Purchase* |
| Research & documents assistant | *Review documents and write a summary* (your documents, wiki pages, wiki write); *Web research*; *Report* |

The right-hand panel shows exactly what the checkpoint will allow, and what is not connected at all: the real internet, real e-mail, payments, your computer's files, external apps.

## 3. Add documents (optional)
- Drag text files in, or click **Add sample documents**. The samples are synthetic and include a deliberately poisoned supplier quote.
- Formats: .txt .md .csv .json .log, up to 100 KB each, 10 files.
- Credentials are refused, and ID- or card-like numbers produce a warning. Use synthetic or sanitized content only.
- **Check for hidden instructions** previews the detector's score. The real protection is the scan when an agent actually reads the document.

## 4. Choose how it runs
| Mode | What happens | Side effects |
|---|---|---|
| **Dry run** | Your plan is decided step by step, in order, on a copy of the live state | None. Document scanning doesn't run here: it needs real tool output |
| **Run my steps** | Each step goes through the real checkpoint to the mock tools | Recorded by the mock tool server. Outbound actions are simulated |
| **Live AI agent** | A real model (Groq `openai/gpt-oss-120b`) plans and acts; every call still passes the checkpoint | As above. **Your task text and every document the agent reads are sent to Groq.** You must tick the disclosure box |

To enable the live AI agent, set these in your own terminal, then launch:

```bash
export GROQ_API_KEY=… MANDATE_LLM_CONSENT=1
```

The key is never stored.

## 5. Read the result
- Each step shows what the agent wanted, the decision (**Allowed**, **Held for you**, **Blocked**), the reason in plain language, the document scan (clean, hidden instructions, or could not verify), and what the tool server actually recorded.
- **Held for you:** use **Approve once and run it** or **Reject**, and give a reason, which goes into the audit trail. An approved action runs exactly once, through the checkpoint. If the agent has been quarantined in the meantime, approval is refused until you review the agent and resume it in **Operate → Agents & mandates**.
- Under **Evidence** you'll find the raw decision record, **Open in Decisions**, and **Export verifiable evidence pack**. Check an exported pack offline with:
  ```bash
  python console/verify_evidence_pack.py <file>
  ```
- **Attack map**, **Audit trail** and **Approvals** show the run in context.

## What to try
1. *Review stark_quote_poisoned.txt…* with **Run my steps**. The quote is flagged; the wiki write is held; approve it.
2. Add a step **read HR records**. It is blocked as out of role, and the agent is quarantined.
3. *Compare the supplier quotes, but do not access HR records…* with **Live AI agent**.
