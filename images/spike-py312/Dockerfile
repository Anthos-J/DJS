# Spike image for S1 / S2 / S7 (AM5: python:3.12 containers). Spike harness only, not product code.
# Base pinned by digest (same digest as S3 config/.env PY_IMAGE, python:3.12-slim).
ARG PY_IMAGE=python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# ---- stage 1: fetch and verify the Cedar CLI (experimental, with SymCC) and cvc5 ----
FROM ${PY_IMAGE} AS tools
ARG CEDAR_URL=https://github.com/cedar-policy/cedar/releases/download/cedar-policy-cli-v4.13.0/cedar-policy-cli-experimental-x86_64-unknown-linux-gnu.tar.xz
# Published by the Cedar release (.sha256 asset), fetched 2026-10-15:
ARG CEDAR_SHA256=deb3a8340e357b871eb7c3e2a701f9a4f2e2f8404ec249740b1ed9eef5a0aefe
ARG CVC5_URL=https://github.com/cvc5/cvc5/releases/download/cvc5-1.3.1/cvc5-Linux-x86_64-static.zip
# cvc5 publishes no hash. Pass CVC5_SHA256 to pin it after the first, trust-on-first-use build; it is recorded either way.
# Trust-on-first-use pin: observed on the first build, 2026-10-15 (42,082,562 bytes).
ARG CVC5_SHA256=1a1cda20d2df4938fa4944a69f33ddc9172e319ece0eed0aa09c4d7abede3ed1
COPY fetch_tools.py /fetch_tools.py
RUN python /fetch_tools.py "$CEDAR_URL" "$CEDAR_SHA256" "$CVC5_URL" "$CVC5_SHA256" /opt/tools

# ---- stage 2: runtime ----
FROM ${PY_IMAGE}
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /requirements.txt \
 && pip freeze > /pip_freeze.txt
COPY --from=tools /opt/tools /opt/tools
ENV PATH=/opt/tools/bin:$PATH CVC5=/opt/tools/bin/cvc5 PYTHONUNBUFFERED=1
