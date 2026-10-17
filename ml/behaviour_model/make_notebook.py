"""Writes MANDATE_behaviour_model.ipynb (run: python make_notebook.py)."""
import json

cells = []
def md(s): cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})
def code(s): cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})

md("""
# MANDATE · behaviour model (learns what normal tool use looks like)

**What this trains.** A model of how a *legitimate* agent sequences its tool calls. MANDATE uses its score as a learned
drift signal: "how unlike normal work is this next action?" Hard rules still decide first; the learned score can only
make a decision stricter.

**Data: not ours.** `agentdojo_sequences.jsonl` is exported from the AgentDojo v1.2.2 benchmark (ETH Zurich): the benchmark's
own ground-truth tool-call sequences for 97 user tasks in 4 suites (workspace, travel, banking, slack), and the same tasks
hijacked by the benchmark's injection tasks (949 sequences). The only thing we constructed is *where* the injected calls
are inserted (after the task's first call).

**Honesty rules**
- Train on **benign sequences only** (the model never sees an attack during training).
- **Grouped cross-validation by user task:** a task's benign run and all its hijacked variants are always in the same fold,
  so the model is tested on tasks it has never seen.
- Alert thresholds are calibrated on **out-of-sample benign tasks inside the training folds** (95th percentile), never on test data.
- Every model, including the simple baselines, is reported. If a baseline wins, that's the result.
- Small data: 97 benign tasks. Numbers will be noisy; the notebook reports per-fold spread.

**Runtime:** Colab, CPU is fine (GPU optional). About 5–10 minutes.
**Before running:** upload `agentdojo_sequences.jsonl` (Files panel on the left).
**At the end:** download `mandate_behaviour_model.zip` and send it back.
""")
code("""
import json, math, random, collections, hashlib, numpy as np
SEED = 20261018; random.seed(SEED); np.random.seed(SEED)
rows = [json.loads(l) for l in open("agentdojo_sequences.jsonl")]
print(len(rows), "sequences |", collections.Counter((r["suite"], r["label"]) for r in rows))
print("sha256 of data:", hashlib.sha256(open("agentdojo_sequences.jsonl", "rb").read()).hexdigest())
""")
md("""
## 1 · Representation
Each tool call becomes an **action type**: `kind:sensitivity:content-trust`, for example `read:2:trusted` or `send:1:trusted`.
These are the properties AgentDojo's tools were annotated with (frozen before any run) and the same properties MANDATE
declares for its own tools, so a model trained here can score MANDATE's agents. Tool *names* would not transfer.
Set `REPR = "tool"` to compare with raw tool names. Arguments are not used. Each suite is modelled separately, like a role.
""")
code("""
BOS, EOS = "<s>", "</s>"
REPR = "action"   # "action" (transfers to MANDATE's tools) or "tool" (raw AgentDojo tool names, for comparison)
seq = lambda r: [BOS] + [c[REPR] for c in r["calls"]] + [EOS]
suites = sorted({r["suite"] for r in rows})
def folds(suite, k=5):
    tasks = sorted({r["user_task"] for r in rows if r["suite"] == suite}); random.Random(SEED).shuffle(tasks)
    return [set(tasks[i::k]) for i in range(k)]
""")
md("""
## 2 · Models
1. **Unseen-tool rule** (baseline): flags a sequence that uses a tool never seen in training benign data for this suite.
2. **Bigram Markov model**: P(next tool | previous tool), Laplace-smoothed. Score = the most surprising step (max −log p).
3. **Isolation Forest** on bag-of-tools + bigram counts (scikit-learn).
4. **GRU next-tool model** (PyTorch): a small recurrent network predicting the next tool. Score = max per-step surprisal.
""")
code("""
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score
import torch, torch.nn as nn

class Unseen:
    def fit(self, S): self.v = {t for s in S for t in s}; return self
    def score(self, s): return float(sum(t not in self.v for t in s))

class Markov:
    def fit(self, S, a=0.5):
        self.v = sorted({t for s in S for t in s} | {"<unk>"}); self.c = collections.defaultdict(collections.Counter)
        for s in S:
            for x, y in zip(s, s[1:]): self.c[x][y] += 1
        self.a = a; return self
    def p(self, x, y):
        y = y if y in self.v else "<unk>"; c = self.c.get(x, {}); return (c.get(y, 0) + self.a) / (sum(c.values()) + self.a * len(self.v))
    def steps(self, s): return [-math.log(self.p(x, y)) for x, y in zip(s, s[1:])]
    def score(self, s): return max(self.steps(s))

class IForest:
    def feats(self, s):
        f = collections.Counter(s); f.update(f"{x}>{y}" for x, y in zip(s, s[1:])); return f
    def fit(self, S):
        self.keys = sorted({k for s in S for k in self.feats(s)})
        X = np.array([[self.feats(s).get(k, 0) for k in self.keys] + [sum(v for kk, v in self.feats(s).items() if kk not in self.keys)] for s in S])
        self.m = IsolationForest(n_estimators=300, random_state=SEED).fit(X); return self
    def score(self, s):
        f = self.feats(s); x = np.array([[f.get(k, 0) for k in self.keys] + [sum(v for kk, v in f.items() if kk not in self.keys)]])
        return float(-self.m.score_samples(x)[0])

class GRU:
    def fit(self, S, epochs=200):
        self.v = ["<unk>"] + sorted({t for s in S for t in s}); self.i = {t: n for n, t in enumerate(self.v)}
        torch.manual_seed(SEED); V = len(self.v)
        self.net = nn.ModuleDict({"emb": nn.Embedding(V, 16), "rnn": nn.GRU(16, 32, batch_first=True), "out": nn.Linear(32, V)})
        opt = torch.optim.Adam(self.net.parameters(), lr=0.01); lossf = nn.CrossEntropyLoss()
        data = [torch.tensor([self.i.get(t, 0) for t in s]) for s in S]
        for _ in range(epochs):
            for x in data:
                h, _ = self.net["rnn"](self.net["emb"](x[:-1]).unsqueeze(0)); loss = lossf(self.net["out"](h[0]), x[1:])
                opt.zero_grad(); loss.backward(); opt.step()
        return self
    def score(self, s):
        x = torch.tensor([self.i.get(t, 0) for t in s])
        with torch.no_grad():
            h, _ = self.net["rnn"](self.net["emb"](x[:-1]).unsqueeze(0)); lp = torch.log_softmax(self.net["out"](h[0]), -1)
        return float(max(-lp[n, x[n + 1]].item() for n in range(len(x) - 1)))

MODELS = {"unseen_tool_rule": Unseen, "markov_bigram": Markov, "isolation_forest": IForest, "gru": GRU}
""")
md("""
## 3 · Grouped cross-validation (held-out user tasks)
**Threshold calibration without touching the test fold.** A threshold taken from the very sequences a model was trained on
is too tight (the model has memorised them), and it flags almost every new task. Instead, inside the *training* tasks
only, we hold out each fifth in turn, score it with a model trained on the rest, and set the alert threshold at the 95th
percentile of those out-of-sample benign scores. The test fold is never used.
""")
code("""
def calib(M, train_rows, k=5):
    tasks = sorted({r["user_task"] for r in train_rows}); random.Random(SEED + 1).shuffle(tasks); oos = []
    for i in range(k):
        hold = set(tasks[i::k]); fit = [seq(r) for r in train_rows if r["user_task"] not in hold]
        if not fit or not hold: continue
        m = M().fit(fit); oos += [m.score(seq(r)) for r in train_rows if r["user_task"] in hold]
    return float(np.percentile(oos, 95)) if oos else float("inf")

res = {m: {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "auc": []} for m in MODELS}
per_suite = {}
for suite in suites:
    for k, test_tasks in enumerate(folds(suite)):
        train = [seq(r) for r in rows if r["suite"] == suite and r["label"] == 0 and r["user_task"] not in test_tasks]
        test = [(seq(r), r["label"]) for r in rows if r["suite"] == suite and r["user_task"] in test_tasks]
        for name, M in MODELS.items():
            m = M().fit(train)
            thr = calib(M, [r for r in rows if r["suite"] == suite and r["label"] == 0 and r["user_task"] not in test_tasks])
            sc = [(m.score(s), y) for s, y in test]
            for v, y in sc:
                flag = v > thr
                res[name]["tp" if (flag and y) else "fn" if y else "fp" if flag else "tn"] += 1
            ys = [y for _, y in sc]
            if len(set(ys)) > 1: res[name]["auc"].append(roc_auc_score(ys, [v for v, _ in sc]))
            ps = per_suite.setdefault((suite, name), {"tp": 0, "fn": 0, "fp": 0, "tn": 0})
            for v, y in sc: ps["tp" if (v > thr and y) else "fn" if y else "fp" if v > thr else "tn"] += 1
summary = {}
for name, r in res.items():
    tpr = r["tp"] / max(1, r["tp"] + r["fn"]); fpr = r["fp"] / max(1, r["fp"] + r["tn"])
    summary[name] = {"detection_rate_on_hijacked": round(tpr, 4), "false_alarm_rate_on_heldout_benign": round(fpr, 4),
                     "auc_mean": round(float(np.mean(r["auc"])), 4), "auc_std_across_folds": round(float(np.std(r["auc"])), 4),
                     "hijacked_n": r["tp"] + r["fn"], "benign_n": r["fp"] + r["tn"]}
    print(f"{name:18s}", summary[name])
""")
code("""
print("per suite (detection / false alarms):")
for (suite, name), r in sorted(per_suite.items()):
    print(f"  {suite:10s} {name:18s} {r['tp']}/{r['tp'] + r['fn']} detected · {r['fp']}/{r['fp'] + r['tn']} benign flagged")
""")
md("""
## 4 · Read this before trusting the numbers
- **Hijacked runs often use tools the task never uses** (for example `send_money` in a read-only task), so even the
  unseen-tool rule scores well. The useful question is whether a learned model beats that rule, especially at a low false-alarm rate.
- **97 benign tasks is small.** Watch the AUC spread across folds.
- These are **ground-truth sequences, not live LLM runs.** Real agents add noise (retries, extra reads), and false alarms
  will be higher in practice. MANDATE's live LLM runs are the place to check that.
""")
md("## 5 · Train the final model on ALL benign data and export it for MANDATE (CPU, no GPU needed)")
code("""
import zipfile
best = max(["markov_bigram", "isolation_forest", "gru"], key=lambda n: (summary[n]["auc_mean"], -summary[n]["false_alarm_rate_on_heldout_benign"]))
print("best learned model by AUC:", best, "| baseline for comparison:", summary["unseen_tool_rule"])
export = {"format": "mandate-behaviour-model/2", "representation": REPR, "data": "AgentDojo v1.2.2 ground-truth sequences", "seed": SEED,
          "data_sha256": hashlib.sha256(open("agentdojo_sequences.jsonl", "rb").read()).hexdigest(),
          "cv_summary": summary, "chosen": best, "suites": {}}
for suite in suites:
    S = [seq(r) for r in rows if r["suite"] == suite and r["label"] == 0]
    m = Markov().fit(S); thr = calib(Markov, [r for r in rows if r["suite"] == suite and r["label"] == 0])
    export["suites"][suite] = {"markov": {"vocab": m.v, "counts": {x: dict(c) for x, c in m.c.items()}, "alpha": m.a}, "threshold_p95": thr}
    if best == "gru":
        g = GRU().fit(S); torch.save({"vocab": g.v, "state": g.net.state_dict()}, f"gru_{suite}.pt")
json.dump(export, open("mandate_behaviour_model.json", "w"), indent=1)
with zipfile.ZipFile("mandate_behaviour_model.zip", "w") as z:
    z.write("mandate_behaviour_model.json")
    for suite in suites:
        try: z.write(f"gru_{suite}.pt")
        except FileNotFoundError: pass
print("wrote mandate_behaviour_model.zip")
from google.colab import files; files.download("mandate_behaviour_model.zip")
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
json.dump(nb, open("MANDATE_behaviour_model.ipynb", "w", encoding="utf-8"), indent=1)
print("wrote MANDATE_behaviour_model.ipynb")
