# S4a image: pinned spike image + agentdojo 0.1.35 (LLM-free replay; no API keys used).
FROM mandate-spike-py312:wave2
RUN pip install --no-cache-dir --disable-pip-version-check agentdojo==0.1.35 && pip freeze > /pip_freeze_agentdojo.txt
