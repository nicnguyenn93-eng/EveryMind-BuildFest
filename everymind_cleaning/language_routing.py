"""Offline English/Spanish routing, independent of the selected form language."""

from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
import math
import re


DEFAULT_CONFIDENCE_THRESHOLD = 0.80
DETECTOR_PACKAGE = "lingua-language-detector"
DETECTOR_VERSION = "2.1.1"
SUPPORTED_LANGUAGES = ("en", "es")
# Contacts and numbers provide no useful evidence about the response language.
# This filtering is for language detection only; Presidio sees the full input.
_CONTACTS = re.compile(
    r"(?:https?://|www\.)\S+|[\w.+%\-]+@[\w.\-]+\.[a-z]{2,}"
    r"|\b(?:[a-z0-9\-]+\.)+[a-z]{2,}(?:/\S*)?"
    r"|\+?\d[\d().\s\-]*",
    re.IGNORECASE,
)
_AMBIGUOUS = {"no", "n a", "na", "ok"}


class LanguageDetectionError(ValueError):
    """A safe-to-display detector error containing no response text."""


@dataclass(frozen=True)
class LanguageDecision:
    language: str
    detected_language: str
    language_confidence: float | None
    language_source: str
    language_review_required: bool


def validate_threshold(threshold):
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0.5 < threshold <= 1):
        raise LanguageDetectionError("Language confidence threshold must be greater than 0.5 and at most 1.")
    return float(threshold)


def detector_metadata(threshold=DEFAULT_CONFIDENCE_THRESHOLD):
    threshold = validate_threshold(threshold)
    try:
        version = metadata.version(DETECTOR_PACKAGE)
    except Exception:
        raise LanguageDetectionError(
            "Local language detector is unavailable. Install the pinned requirements before running the pipeline."
        ) from None
    if version != DETECTOR_VERSION:
        raise LanguageDetectionError(f"Local language detector must be version {DETECTOR_VERSION}.")
    return {"package": DETECTOR_PACKAGE, "version": version,
            "languages": list(SUPPORTED_LANGUAGES), "confidence_threshold": threshold}


@lru_cache(maxsize=1)
def get_detector():
    """Load only the two bundled language models, once per process."""
    detector_metadata()
    try:
        from lingua import Language, LanguageDetectorBuilder
        return LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.SPANISH).build()
    except Exception:
        raise LanguageDetectionError("Could not initialize the local English/Spanish language detector.") from None


def resolve_language(text, fallback="unknown", threshold=DEFAULT_CONFIDENCE_THRESHOLD):
    """Return the effective model language and a reviewable routing decision."""
    threshold = validate_threshold(threshold)
    if not text.strip():
        return LanguageDecision("none", "none", None, "blank", False)

    fallback = {"en": "en", "es": "es", "english": "en", "spanish": "es"}.get(
        str(fallback).strip().casefold(), "unknown"
    )
    linguistic_text = _CONTACTS.sub(" ", text)
    key = " ".join(re.findall(r"[^\W\d_]+", linguistic_text.casefold()))
    detected, confidence = "unknown", None
    if key and key not in _AMBIGUOUS:
        try:
            scores = [(s.language.iso_code_639_1.name.lower(), float(s.value))
                      for s in get_detector().compute_language_confidence_values(linguistic_text)]
            if (len(scores) != 2 or {code for code, _ in scores} != set(SUPPORTED_LANGUAGES)
                    or any(not math.isfinite(score) or not 0 <= score <= 1 for _, score in scores)):
                raise ValueError("Invalid language scores")
            detected, confidence = max(scores, key=lambda item: item[1])
        except LanguageDetectionError:
            raise
        except Exception:
            raise LanguageDetectionError("Local language detection failed; no results published.") from None
        if confidence >= threshold:
            return LanguageDecision(detected, detected, confidence, "text", False)

    source = "form_fallback" if fallback in SUPPORTED_LANGUAGES else "unresolved"
    return LanguageDecision(fallback, detected, confidence, source, True)
