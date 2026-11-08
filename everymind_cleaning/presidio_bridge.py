"""Adapt the existing local Presidio engine to John's batch privacy contract."""

from dataclasses import asdict
from functools import lru_cache

from everymind_censoring.redact_pii import Redaction, RedactionError, build_redactor


@lru_cache(maxsize=1)
def get_engine():
    """Load both CPU models once per process; setup downloads remain separate."""
    return build_redactor()


class PresidioBridge:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else get_engine()
        self.versions = self.engine.versions
        self.last_review = None

    def __call__(self, texts, languages):
        self.last_review = None
        if len(texts) != len(languages):
            raise RedactionError("Presidio requires one language per comment.")
        # Validate the entire batch before detecting anything.
        for number, (text, language) in enumerate(zip(texts, languages), start=1):
            if not isinstance(text, str):
                raise RedactionError(f"Comment {number} must be text.")
            if text.strip() and language not in ("en", "es"):
                raise RedactionError(f"Unsupported language for nonblank comment {number}; expected en or es.")
        output, details = [], []
        for number, (text, language) in enumerate(zip(texts, languages), start=1):
            if not text.strip():
                result = Redaction(text, [])
                status = "blank"
            else:
                try:
                    result = self.engine.redact(text, language)
                except Exception:
                    raise RedactionError(f"Presidio processing failed at comment {number}; no results published.") from None
                status = "changed" if result.text != text else "unchanged"
            output.append(result.text)
            details.append({"status": status, "detections": [asdict(d) for d in result.detections]})
        self.last_review = details
        return output


def connect():
    """Connect the same package adapter used by the CLI and notebook."""
    from . import privacy_adapter
    bridge = PresidioBridge()
    privacy_adapter.connect(bridge, "local Presidio baseline (review required)")
    return bridge
