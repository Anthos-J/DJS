# MANDATE behaviour model: train it yourself

## Files
| File | What it is |
|---|---|
| `MANDATE_behaviour_model.ipynb` | The Colab notebook. Upload it to Colab and run every cell top to bottom. |
| `agentdojo_sequences.jsonl` | Training and test data (upload it to Colab too). sha256 `00c3c36b…3c99` (v2: each call also carries its action type). |
| `export_agentdojo.py` | How the data was exported from AgentDojo v1.2.2 (ETH Zurich), offline, with no LLM. |
| `make_notebook.py` | Generates the notebook (so its contents are reviewable as code). |

## Steps
1. Go to colab.research.google.com, then File → Upload notebook → `MANDATE_behaviour_model.ipynb`.
2. Files panel (left) → upload `agentdojo_sequences.jsonl`.
3. Runtime → Run all. CPU is fine, about 5–10 minutes.
4. The last cell downloads `mandate_behaviour_model.zip`. Put it in this folder and tell Claude.

## What to expect (a local quick check with a short training run; your full run will differ a little)
Representation: **action types** (`kind:sensitivity:content-trust`, for example `read:2:untrusted`) from the frozen AgentDojo tool annotations. These are the same properties MANDATE declares for its own tools, so the model applies to MANDATE's agents. Tool names would not transfer.

| Model | Hijacked runs flagged | Legit runs wrongly flagged | AUC |
|---|---|---|---|
| Unseen-action rule (baseline) | 6% | 1% | 0.54 |
| Markov bigram | 20% | 4% | 0.74 |
| Isolation Forest | 16% | 12% | 0.64 |
| GRU | 24% | 11% | 0.74 |

**The honest reading.** On tasks it has never seen, the learned model catches about 1 in 5 hijacked runs while rarely flagging legitimate ones. That makes it a supporting signal, not a detector you'd trust alone. MANDATE uses it only to make decisions stricter; the hard mandate rules do the heavy lifting.

The first trained model (tool-name representation, 18 Oct) is superseded: it could not score MANDATE's tools.
