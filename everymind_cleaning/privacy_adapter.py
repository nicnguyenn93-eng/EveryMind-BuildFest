"""
privacy_adapter.py - batch boundary for the team's privacy tool.

The privacy tool (Presidio-based) is owned by another teammate. This file is
the only place the cleaning pipeline touches it, so swapping in the real tool
is a one-line change and nothing else in the pipeline needs to know how
redaction works.

Contract the privacy tool must satisfy
--------------------------------------
    redact(texts: list[str], languages: list[str]) -> list[str]

    * same length and order as `texts`
    * `languages[i]` is "en", "es", "unknown", or "none" for blank texts
    * empty strings come back as empty strings
    * redaction is best effort; output still requires local review

How to connect it (pick one)
----------------------------
    import privacy_adapter
    from their_module import redact          # teammate's function
    privacy_adapter.connect(redact)

or set PRIVACY_TOOL_IMPORT below to "their_module:redact".

Until a tool is connected, is_connected() is False and the pipeline:
    * keeps raw comments only in the private output folder
    * leaves the public `__redacted` columns empty, marked "pending"
    * refuses to send any comment text to an LLM (translation etc.)
"""
from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Callable, Optional

# Optional "module:function" path, e.g. "privacy_tool:redact". Leave None to use connect().
PRIVACY_TOOL_IMPORT: Optional[str] = None

_redact_fn: Optional[Callable[[list, list], list]] = None
_tool_name: str = "not connected"


def connect(fn: Callable[[list, list], list], name: str | None = None) -> None:
    """Register the teammate's redaction function."""
    global _redact_fn, _tool_name
    if not callable(fn):
        raise TypeError("connect() expects a callable redact(texts, languages) -> list[str]")
    _redact_fn = fn
    _tool_name = name or getattr(fn, "__module__", "") + "." + getattr(fn, "__name__", "redact")


def disconnect() -> None:
    global _redact_fn, _tool_name
    _redact_fn, _tool_name = None, "not connected"


@contextmanager
def using(fn=None, name=None):
    """Temporarily replace the adapter, restoring it even when a check fails."""
    global _redact_fn, _tool_name, PRIVACY_TOOL_IMPORT
    previous = (_redact_fn, _tool_name, PRIVACY_TOOL_IMPORT)
    PRIVACY_TOOL_IMPORT = None
    disconnect()
    if fn is not None:
        connect(fn, name)
    try:
        yield
    finally:
        _redact_fn, _tool_name, PRIVACY_TOOL_IMPORT = previous


def review_details():
    """Optional per-item detections from the most recent batch."""
    return getattr(_redact_fn, "last_review", None)


def versions():
    return getattr(_redact_fn, "versions", {})


def _try_import() -> None:
    if _redact_fn is None and PRIVACY_TOOL_IMPORT:
        module_name, fn_name = PRIVACY_TOOL_IMPORT.split(":")
        connect(getattr(importlib.import_module(module_name), fn_name), PRIVACY_TOOL_IMPORT)


def is_connected() -> bool:
    _try_import()
    return _redact_fn is not None


def tool_name() -> str:
    _try_import()
    return _tool_name


def redact_texts(texts: list, languages: list) -> Optional[list]:
    """Return redacted texts, or None if no privacy tool is connected."""
    if len(texts) != len(languages):
        raise ValueError("Privacy tool requires one language per text")
    if not is_connected():
        return None
    out = _redact_fn(list(texts), list(languages))
    # enforce the contract so a broken tool fails loudly instead of misaligning rows
    if not isinstance(out, (list, tuple)) or len(out) != len(texts):
        raise ValueError(
            f"Privacy tool returned {type(out).__name__} of length "
            f"{len(out) if hasattr(out, '__len__') else '?'}; expected list of length {len(texts)}"
        )
    if any(not isinstance(t, str) for t in out):
        raise ValueError("Privacy tool must return strings only")
    return list(out)
