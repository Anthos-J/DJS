# Control-plane image for engine E4.3: the validated spike image plus the CPU runtime for the owner-trained
# injection detector (config/injection_model). Pinned versions; nothing else changes.
FROM mandate-spike-py312:wave2
RUN pip install --no-cache-dir "onnxruntime==1.20.1" "tokenizers==0.21.0" "numpy==2.2.1"
