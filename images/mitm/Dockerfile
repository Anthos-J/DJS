# S5/S6 image: the pinned spike image + curl + mitmproxy 12.2.3 (requires Python >= 3.12).
# Base: local spike image; build.sh checks its ID is sha256:44bc7e002d45... before building.
FROM mandate-spike-py312:wave2
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --disable-pip-version-check mitmproxy==12.2.3 && pip freeze > /pip_freeze_mitm.txt
