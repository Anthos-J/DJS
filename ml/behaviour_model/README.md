# MANDATE behaviour model: train it yourself

## Files
| File | What it is |
|---|---|
| `MANDATE_behaviour_model.ipynb` | The Colab notebook. Upload it to Colab and run every cell top to bottom. |
| `agentdojo_sequences.jsonl` | Training and test data (upload it to Colab too). sha256 `84afdc39…15de`. |
| `export_agentdojo.py` | How the data was exported from AgentDojo v1.2.2 (ETH Zurich), offline, with no LLM. |
| `make_notebook.py` | Generates the notebook (so its contents are reviewable as code). |

## Steps
1. Go to colab.research.google.com, then File → Upload notebook → `MANDATE_behaviour_model.ipynb`.
2. Files panel (left) → upload `agentdojo_sequences.jsonl`.
3. Runtime → Run all. CPU is fine, about 5–10 minutes.
4. The last cell downloads `mandate_behaviour_model.zip`. Put it in this folder and tell Claude.

## What to expect (a local quick check with a short training run; your full run will differ a little)
The data is small: 97 benign tasks across 4 suites, and 949 hijacked variants. Tested on user tasks the model never saw:

| Model | Hijacked runs flagged | Legit runs wrongly flagged | AUC |
|---|---|---|---|
| Unseen-tool rule (baseline) | 6% | 2% | 0.59 |
| Markov bigram | 27% | 18% | 0.70 |
| Isolation Forest | 11% | 11% | 0.60 |
| GRU | 17% | 9% | 0.71 |

**The honest reading.** On tasks it has never seen, a sequence model is a *weak* signal: it beats the simple rule, but it misses most hijacks. That is why MANDATE uses it only to make decisions stricter, never on its own, and why the hard mandate rules do the heavy lifting. Present it in the deck exactly like that.
