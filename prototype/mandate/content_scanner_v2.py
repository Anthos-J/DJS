"""MANDATE content scanner v2 (engine E4.3.1). Same owner-trained ONNX model and threshold as E4.3; fixes two scanner flaws.

1. Token windows, not characters. E4.3's scanner decided "short enough for one pass" by CHARACTER count and then let the
   tokenizer truncate at 384 tokens, so text after token 384 of a ~1,500-character document was never scored; its word
   windows (480 words) were also longer than 384 tokens. v2 tokenizes the whole text once, without truncation, and scores
   overlapping windows of at most MAX_TOKENS tokens (382 content tokens + [CLS] + [SEP]); every token is in some window.
2. Never "clean" by default. Every result carries a status:
     "ok"         every window was scored; injection = (max window score >= threshold)
     "error"      tokenizing or scoring failed            -> verified = False
     "too_long"   more than MAX_WINDOWS windows needed    -> verified = False (the unscored tail is not assumed safe)
     "disabled"   model not loaded                        -> verified = False
   The engine (E4.3.1 observe_content) treats verified = False like a flag: the session is marked untrusted.
Empty or whitespace-only text has nothing to scan: status "ok", verified = True, injection = False.
"""
import json, logging
from pathlib import Path

logger = logging.getLogger("mandate.content_scanner_v2")
MAX_TOKENS = 384              # the model was trained at 384 tokens
STRIDE = 318                  # window step: 64 tokens of overlap between neighbouring windows
MAX_WINDOWS = 64              # ~20,000 tokens; longer text is reported as too_long (unverified), never silently cut
CLS, SEP = 1, 2               # DeBERTa-v3 special token ids (config.json bos/eos)

try:
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    _HAVE = True
except Exception:              # the engine reports the detector as not loaded; E4.3.1's launcher gate refuses to start
    _HAVE = False


class TokenWindowScanner:
    def __init__(self, model_dir, threshold=0.5):
        self.model_dir, self.threshold, self.provenance, self._loaded = Path(model_dir), threshold, None, False
        if not _HAVE or not (self.model_dir / "model.onnx").exists():
            return
        try:
            o = ort.SessionOptions(); o.intra_op_num_threads = 2; o.log_severity_level = 3
            self.session = ort.InferenceSession(str(self.model_dir / "model.onnx"), o, providers=["CPUExecutionProvider"])
            self.tok = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
            self.tok.no_padding(); self.tok.no_truncation()
            self.inputs = {i.name for i in self.session.get_inputs()}
            p = self.model_dir / "provenance.json"
            self.provenance = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            self._loaded = True
        except Exception as e:
            logger.warning(f"content scanner v2 failed to load: {type(e).__name__}: {e}")

    @property
    def enabled(self):
        return self._loaded

    def _score(self, ids):
        feed = {"input_ids": np.array([ids], dtype=np.int64), "attention_mask": np.ones((1, len(ids)), dtype=np.int64)}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros((1, len(ids)), dtype=np.int64)
        lo = self.session.run(None, feed)[0][0].astype(np.float64)
        p = np.exp(lo - lo.max()); p /= p.sum()
        return float(p[1])

    def windows(self, n):
        body = MAX_TOKENS - 2
        if n <= body:
            return [(0, n)]
        starts = list(range(0, n - body, STRIDE)) + [n - body]     # the last window always ends at the final token
        return [(s, s + body) for s in sorted(set(starts))]

    def scan_document(self, text):
        base = {"threshold": self.threshold, "windows": 0, "tokens": 0}
        if not self._loaded:
            return {**base, "status": "disabled", "verified": False, "injection": False, "score": None}
        if text is None or (isinstance(text, str) and not text.strip()):
            return {**base, "status": "ok", "verified": True, "injection": False, "score": 0.0}
        try:
            if not isinstance(text, str):
                text = str(text)
            ids = self.tok.encode(text.replace("\x00", " "), add_special_tokens=False).ids
            spans = self.windows(len(ids))
            if len(spans) > MAX_WINDOWS:
                return {**base, "tokens": len(ids), "status": "too_long", "verified": False, "injection": False, "score": None,
                        "detail": f"{len(spans)} windows needed, limit {MAX_WINDOWS}"}
            best, where = 0.0, None
            for s, e in spans:
                sc = self._score([CLS] + ids[s:e] + [SEP])
                if sc > best:
                    best, where = sc, [s, e]
            return {**base, "tokens": len(ids), "windows": len(spans), "status": "ok", "verified": True,
                    "injection": best >= self.threshold, "score": round(best, 4), "worst_window": where}
        except Exception as e:                                   # fail closed: an unscorable document is NOT clean
            return {**base, "status": "error", "verified": False, "injection": False, "score": None, "detail": f"{type(e).__name__}: {str(e)[:160]}"}

    def status(self):
        return {"enabled": self._loaded, "threshold": self.threshold, "max_tokens": MAX_TOKENS, "stride": STRIDE, "max_windows": MAX_WINDOWS}
