# Release R-E4.3.1: engine E4.3.1 and the "Your task" workbench

**Engine:** `engine-E4.3.1` (`908d084`, `FROZEN_E431.sha256`). E4.3 (`engine-E4.3`) and all earlier engines are unchanged and selectable with `MANDATE_ENGINE`. The launcher and console now default to E4.3.1.
**Scope:** AI-assisted build and self-review on one Windows 11 + Docker Desktop machine. Not independent, not SECURITY-TESTED, not production-ready.

## 1. Why a successor engine

A post-release review (findings F-01 to F-08) found two detector flaws in frozen E4.3. Fixing them changes detector behaviour, so the fix is a new version, not an edit to E4.3.

| Finding | Verified? | What E4.3.1 does |
|---|---|---|
| **F-01** E4.3 checked document length in characters, then let the tokenizer cut at 384 tokens, so an injection after token 384 of a ~1.1–1.9k-character document was never scored | **Yes**, with the real model: E4.3 missed it and E4.3.1 caught it for every tested length from 1,095 to 1,875 characters (`TestRealModelV2`) | `content_scanner_v2.py` tokenizes the whole text and scores overlapping 384-token windows; every token is in some window |
| **F-02 / D3** a scoring exception returned "not flagged" (fail open) | **Yes** (code) | Any unverifiable result taints the session, and the alert says "could not verify": a scanner error, more than 64 windows, a detector that is not loaded, or text the PEP reports as truncated (over 200,000 characters) |
| F-03 missing `cedarpy` makes every consequential action DENY | True. This is fail-closed by design | Unchanged. The tests run in the pinned image, which has Cedar |
| F-04 the tools are mocks | True, and documented | Unchanged |
| F-05 the guided stories are scripted | True, and documented | The workbench adds user-defined tasks and the live AI agent |
| F-06 structured records are not scanned (D1) | True | Unchanged (a documented limitation) |
| F-07 the sequence model has 0 points | True, by decision | Unchanged |
| F-08 the deck's slide 1 has placeholders | True | Needs the team's names and college. Not filled in (we don't have them) |

**Also found:** an **unversioned, uncommitted edit to frozen `content_scanner.py`**. It partly addressed F-01, but it still returned "clean" on errors while its log message said "fail closed". It was saved to `docs/unversioned_patches/20261018-content_scanner-uncommitted-edit.patch` and the frozen file was restored byte-for-byte.

**Decision logic unchanged.** On fresh seeds 971–975, E4.3.1 (two runs) and E4.3 give an **identical decision hash** (`1ac9ef91a24c`): 30 of 1,260 attacks succeeded (all C4), 0 of 840 legitimate tasks were denied, and 124 needed approval. The 60-test E4.2.1 rule suite passes on E4.3.1. The scenarios contain no documents, so this evaluation does not exercise the detector. The detector fixes are evidenced by their own tests.

## 2. The workbench ("Your task" in the console)

What it adds:
- You can describe a task, pick an agent and a job from the role catalogue, add your own sanitized text documents, and run the task.
- **Dry run:** a side-effect-free plan check using the plan simulator.
- **Run my steps:** the real PEP path to the mock tools.
- **Live AI agent:** Groq, opt-in, with disclosure required.

Every result is read back from the control plane and the tool server. How to use it: `docs/WORKBENCH.md`.

**Security properties, and the test that checks each** (`e2e/workbench_e2e.py`, `console/tests/test_workbench_unit.py`, `tests/test_engine_e431.py`):

| Property | Test |
|---|---|
| Every protected action goes cell → sidecar → mTLS → PEP → control → tool server. The workbench never calls the tool server itself | unit `test_steps_go_only_through_agent_call…`; E2E W14 (every effect carries its PEP decision id) |
| Documents are readable only through the PEP. The workspace is mounted read-only into the tool server and into no agent cell | E2E W7 |
| The instruction grants nothing: tools, data, destinations and HR scope come from the catalogue. An amount written in the instruction counts as the owner's authorisation for that exact value | E2E W20 and W20b; engine `TestInstructionGrantsNothing`, `test_document_cannot_change_the_authorised_amount` |
| Arguments reserved for the PEP (`_approval`, `_delegation`) cannot be set by a task | E2E W8; unit test |
| The dry run executes nothing. Its only audit records are the owner's setup | E2E W9 and W10 |
| A document is scanned on the real path. A flagged or unverifiable document taints the session, so later writes are held | E2E W11–W13; engine `TestFailClosed`, `TestWorkspaceTools` |
| Approvals go through the existing API, run once, can't be reused, can't be resolved through another run, and are refused while the agent is quarantined | E2E W15–W19, W20c |
| Input validation: name, extension, size, empty files, credential patterns, CSRF, malformed JSON, length limits | E2E W3–W5, W8; unit `TestDocs` |
| Provider failure, timeout and malformed model output stop cleanly with no tool calls, or go through the PEP | unit `test_provider_failure…`, `test_provider_timeout`, `test_malformed_model_output…`, `test_turn_limit` |
| Evidence packs export and self-verify; the audit chain still verifies | E2E W21 and W22 |
| Live AI: the poisoned document is flagged when read, and no HR read, e-mail or unapproved write occurs | E2E W23 and W24 (live Groq) |

## 3. Results

| Check | Result | Evidence |
|---|---|---|
| Unit suites (control image, `--network none`) | E4.3.1 26/26 + rules 60/60; E4.3 34 + 60; E1–E4.2.1 13/9/22/33/35/58/60; cross-engine 19/22 and 39/44 (as recorded) | `tests/runs/*-regression-E431/results.txt` |
| Workbench unit (host) | 12/12 | same file |
| Live E2E | 17/17 on E4.3.1 and on E4.3 | `e2e/runs/20261018T154039-e2e`, `…154158-e2e` |
| Workbench E2E (live stack, live Groq) | 26/26. Earlier attempts were 20/23 then 24/25 because the test mixed attacks into a legitimate run, and the agent was rightly quarantined. They are kept | `e2e/runs/*-workbench/` |
| Console integration | 21/21 | `console/tests/runs/20261018T154656` |
| Fresh evaluation | E4.3.1 = E4.3, hash identical | `eval/runs/20261018T1600-*-s97x-*` |
| Browser walk-through | composer, examples, sample documents, steps run, held write approved once with a reason, live AI run, disclosure refusal, mobile width (no horizontal overflow) | this release |

## 4. Limitations (new or confirmed)

- **W1** The benign sample `security_notice.txt` ("Ignore this message if you have already completed it…") **is flagged as an injection (0.87)**. That is a false positive on instruction-like text. The threshold was not changed to hide it.
- **W2** Documents are plain text only (.txt .md .csv .json .log, 100 KB each, 10 files). There is no PDF or Office parsing.
- **W3** Two fixed agent profiles (procurement and research) and six tasks. Users cannot define new roles, by design: the catalogue is the authority.
- **W4** The tools are mocks. Web, e-mail, upload and purchase are simulated or recorded only.
- **W5** In live-AI mode the task text and every document the agent reads are sent to Groq. It is opt-in, with a disclosure checkbox.
- **W6** After you approve a held action, it runs once. The AI agent does not continue the task afterwards: the run has already finished.
- **W7** Keyword hints before a run are hints only. The checkpoint decides, action by action.
- **W8** A workbench run first sets the chosen agent active and assigns the task. These are owner actions and are audited. This can lift an earlier quarantine of that demo agent.
- D1 (records not scanned), D2 (detector misses), D5 (small live sample) and D6 (dataset licences) still apply. **D3 (fail-open on scoring error) is fixed in E4.3.1.**
