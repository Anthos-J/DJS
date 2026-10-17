# MANDATE prompt-injection detector: train it yourself

## Files
| File | What it is |
|---|---|
| `MANDATE_injection_detector.ipynb` | The Colab notebook. Upload it to Colab and run every cell top to bottom. |
| `make_notebook.py` | Generates the notebook (so its contents are reviewable as code). |

## Steps
1. Go to colab.research.google.com, then File → Upload notebook → `MANDATE_injection_detector.ipynb`.
2. Change runtime to **GPU** (T4 is fine, and free).
3. Runtime → Run all. ~20–30 minutes on a T4.
4. The last cell downloads `mandate_injection_detector.zip`. Put it in this folder and unzip it.
5. Tell Claude/Antigravity to integrate it into MANDATE.

## What it trains
- **Model:** `microsoft/deberta-v3-small` (44M params), fine-tuned as a binary classifier.
- **Dataset:** `deepset/prompt-injections` from Hugging Face — a public, externally-authored, CC-BY-4.0 dataset. We did NOT author any of the training data.
- **Task:** Detect hidden prompt-injection attacks inside text that an AI agent reads.
- **Output:** ONNX file (~180 MB) runnable with `onnxruntime` on CPU. No GPU needed at inference.

## What to expect
The notebook reports precision, recall, F1, and a confusion matrix on the held-out test split.
Expected performance (the exact numbers depend on your training run):

| Metric | Keyword baseline | DeBERTa (ours) |
|---|---|---|
| Precision | ~0.50–0.70 | ~0.95+ |
| Recall | ~0.30–0.50 | ~0.90+ |
| F1 | ~0.35–0.55 | ~0.92+ |

## How MANDATE uses it
Every document an agent opens (supplier quotes, web pages, emails) is scanned by the ONNX model
**before the agent reads the content**. If a prompt injection is detected:
1. A `content_injection_detected` factor is added to the risk score (40 points).
2. The session's integrity is set to `untrusted` (same as reading from an untrusted source).
3. For high-sensitivity resources, the read is held for owner approval.
4. For consequential follow-up actions, the tainted-sensitive-flow rule kicks in.

The model can only make decisions **stricter** — hard rules still decide first.
