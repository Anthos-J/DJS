"""Export AgentDojo v1.2.2 ground-truth tool-call sequences (authored by the AgentDojo team, ETH Zurich) for training
MANDATE's behaviour model. No LLM, no network. One JSON line per sequence:
  {"suite", "user_task", "injection_task" (null for benign), "label": 0 benign / 1 injected, "calls": [{"tool","args"}...]}
Injected sequence = the user task's ground truth with the injection task's ground-truth calls inserted after the first
call that reads injectable content (or appended), mirroring how an injection hijacks an agent mid-task."""
import copy, json, sys
from agentdojo.task_suite.load_suites import get_suite

def ser(c):
    a = {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in dict(c.args).items()}
    return {"tool": c.function, "args": a}

out = open(sys.argv[1], "w")
n = {"benign": 0, "injected": 0}
for sname in ["workspace", "travel", "banking", "slack"]:
    suite = get_suite("v1.2.2", sname)
    env = suite.load_and_inject_default_environment(suite.get_injection_vector_defaults())
    for uid, ut in suite.user_tasks.items():
        cu = [ser(c) for c in ut.ground_truth(copy.deepcopy(env))]
        out.write(json.dumps({"suite": sname, "user_task": uid, "injection_task": None, "label": 0, "calls": cu}) + "\n"); n["benign"] += 1
        for iid, it in suite.injection_tasks.items():
            ci = [ser(c) for c in it.ground_truth(copy.deepcopy(env))]
            k = 1 if cu else 0
            out.write(json.dumps({"suite": sname, "user_task": uid, "injection_task": iid, "label": 1, "calls": cu[:k] + ci + cu[k:]}) + "\n"); n["injected"] += 1
print(json.dumps(n))
