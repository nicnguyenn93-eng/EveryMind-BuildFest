"""Frontend-independent analysis and Gemini reports from verified censored data.

Both public functions return JSON-compatible dictionaries. They never run the
cleaner, read original-comment sidecars, or write application/session state.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from analysis import AUDIENCES
from cleaned_analysis import run as analyze_censored_export
from everymind_cleaning.censored_data import CensoredExportError
from report import DEFAULT_MODEL, Finding, Recommendation, draft_report_from_payload


CATALOG_PATH = Path(__file__).with_name("action_catalog.json")
REPORT_SCHEMA = "everymind.report.v1"


class ReportRecommendation(Recommendation):
    model_config = ConfigDict(extra="forbid")
    proposed_action: str
    staff_owner: str


class ReportResult(BaseModel):
    """Versioned JSON boundary consumed by an independently developed frontend."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["everymind.report.v1"]
    dataset_key: str = Field(pattern=r"^censored-sha256:[0-9a-f]{64}$")
    audience: str
    mode: Literal["llm", "template"]
    summary_blocks: list[str]
    evidence_ids: list[str]
    proposed_action_id: str | None
    proposed_action: str | None
    staff_owner: str | None
    follow_up_measure: str | None
    limitations: str
    summary: list[Finding]
    proposed_recommendations: list[ReportRecommendation]
    model: str | None
    fallback_reason: str | None


class ReportServiceError(ValueError):
    """Safe-to-display input error; provider failures return template reports."""


def get_analysis(censored_path, audience="All respondents", *, reviews=None):
    """Read the full censored CSV/manifest and return everymind.analysis.v2.

    ``reviews`` is an optional in-memory list of explicit human review records.
    Omitting it keeps comment evidence unavailable. Raw exports, cleaned-only
    checkpoints, incomplete/tampered exports, and duplicate IDs are rejected.
    """
    if audience not in AUDIENCES:
        raise ReportServiceError("Choose a supported audience from analysis.AUDIENCES.")
    try:
        payload = analyze_censored_export(censored_path, audience, reviews)
        json.dumps(payload, allow_nan=False)
    except CensoredExportError as error:
        raise ReportServiceError(str(error)) from None
    except (ValueError, TypeError, KeyError, OSError):
        raise ReportServiceError(
            "Analysis validation failed. Check unique response IDs and current review records."
        ) from None
    return payload


def generate_report(censored_path, audience="All respondents", *,
                    expected_dataset_key=None, reviews=None,
                    include_approved_comments=False, api_key=None,
                    model=DEFAULT_MODEL, use_llm=True, retries=1, client=None):
    """Return everymind.report.v1 from the current verified censored export.

    Pass the key returned by get_analysis as ``expected_dataset_key`` to reject
    data that changed while a user was viewing it. Set ``use_llm=False`` for an
    offline template. API credentials are passed directly or read from the
    environment by report.py; they never enter the returned dictionary.

    Aggregate-only is the default. Explicitly enabling comments still requires
    current, privacy-screened human approvals; Presidio alone is insufficient.
    """
    payload = get_analysis(censored_path, audience, reviews=reviews)
    if expected_dataset_key is not None and expected_dataset_key != payload["dataset_key"]:
        raise ReportServiceError("The censored dataset changed. Reload analysis before generating a report.")
    if not isinstance(model, str) or not model.strip():
        raise ReportServiceError("Choose a nonblank Gemini model name.")
    if not isinstance(include_approved_comments, bool) or not isinstance(use_llm, bool):
        raise ReportServiceError("Comment inclusion and LLM flags must be booleans.")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 2:
        raise ReportServiceError("Report retries must be an integer between 0 and 2.")
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ReportServiceError("The report action catalog is unavailable.") from None
    result = draft_report_from_payload(
        payload, catalog, include_approved_comments=include_approved_comments,
        api_key=api_key, model=model, use_llm=use_llm, retries=retries, client=client,
    )
    result = ReportResult.model_validate(dict(result, schema_version=REPORT_SCHEMA)).model_dump()
    json.dumps(result, allow_nan=False)
    return result
