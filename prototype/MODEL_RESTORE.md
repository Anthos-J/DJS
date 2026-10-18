# E4.3 injection-detector model: storage, integrity and restore

| | |
|---|---|
| File | `prototype/config/injection_model/model.onnx` (568,132,120 bytes) |
| Expected sha256 | `c69d502df27acbfac888a43cf77092da332de80af670c42bbe74b7a9c6fdae1c` (from `FROZEN_E43.sha256`, frozen at `engine-E4.3`) |
| In git | No (too large). The four small files beside it (tokenizer, configs, provenance) are in git. |
| Delivered as | `MANDATE_E4.3_injection_model.zip` beside the submission ZIP, with its own `.sha256` |
| Owner's original | `ml/injection_detector/mandate_injection_detector (1).zip` (Colab output, sha256 `95c87f88…f6a5`); restore works from it too |

## Restore

From `validation/`:

```bash
python tools/restore_injection_model.py MANDATE_E4.3_injection_model.zip
```

It checks the archive before installing anything:
- The expected hash is read from `prototype/FROZEN_E43.sha256`, not from the archive.
- `model.onnx` is hashed while it is extracted to a temporary file.
- It is moved into place only if the hash matches. On any mismatch, nothing is installed and the exit code is 2.

To check an installed model:

```bash
python tools/restore_injection_model.py - --check
```

## Fail-closed behaviour when the model is missing or wrong

- `run_prototype.sh`, used by `demo/launch.sh` and the console's Reset, refuses to deploy E4.3 (exit 5) unless `model.onnx` matches the frozen hash.
- After start-up, it tears the stack down (exit 6) unless the running control plane reports the detector as loaded (`/api/meta` → `injection_detector.enabled`).
- So E4.3 never runs silently without document scanning.
- Earlier engines (`MANDATE_ENGINE=E4.2.1`, and so on) do not use the model and start without it.

**Fixed in E4.3.1:** a document that cannot be scored is treated as untrusted. This covers an exception, too-long text, PEP truncation and a missing detector (`RELEASE_E431.md`). **E4.3 residual (frozen code):** if the model is loaded but scoring one document throws an exception at runtime, `content_scanner.py` logs it and treats that document as not flagged. That is fail-open for that one document. The PEP still fails closed if the control plane cannot be reached for the scan. Changing the exception behaviour would change detector behaviour, so it would need a new engine version and a new evaluation.

## Source and licences

| Component | Source | Licence (as declared on Hugging Face, checked 18 Oct 2026) |
|---|---|---|
| Base model | `microsoft/deberta-v3-small` | MIT |
| Training data | `deepset/prompt-injections` | Apache-2.0 |
| Training data | `xTRam1/safe-guard-prompt-injection` | **none declared** |
| Training data | `SetFit/enron_spam` (Enron e-mails, clean and with an inserted dataset injection) | **none declared** (the Enron corpus was made public through the FERC investigation) |
| Test only | `abisee/cnn_dailymail` | Apache-2.0 |
| Test only | `Lakera/gandalf_ignore_instructions` | MIT |

**Redistribution.** Two training datasets declare no licence, so the terms for redistributing weights trained on them are unclear. For that reason the model is delivered as a separate archive for evaluating this submission, and is not published openly. Publishing it more widely is the owner's decision, after checking those terms. The weights were fine-tuned by the owner on Google Colab with `ml/injection_detector/MANDATE_injection_detector.ipynb` (run 3).
