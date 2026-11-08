"""Frontend-independent analysis and Gemini reports from verified censored data.

Both public functions return JSON-compatible dictionaries. They never run the
cleaner, read original-comment sidecars, or write application/session state.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from analysis import AUDIENCES
from cleaned_analysis import analyze_export
from censored_comment_evidence import build_censored_comment_evidence, INPUT_POLICY
from everymind_cleaning.censored_data import CensoredExportError, load_censored_export
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
    input_policy: Literal["aggregate_only", "reviewed_comments", "censored_comments_v1"] = "aggregate_only"
    censored_comment_count: int = Field(default=0, ge=0)


class ReportServiceError(ValueError):
    """Safe-to-display input error; provider failures return template reports."""


def _load_analysis(censored_path, audience, reviews):
    if audience not in AUDIENCES:
        raise ReportServiceError("Choose a supported audience from analysis.AUDIENCES.")
    try:
        export = load_censored_export(censored_path)
        payload = analyze_export(export, audience, reviews)
        json.dumps(payload, allow_nan=False)
    except CensoredExportError as error:
        raise ReportServiceError(str(error)) from None
    except (ValueError, TypeError, KeyError, OSError):
        raise ReportServiceError(
            "Analysis validation failed. Check unique response IDs and current review records."
        ) from None
    return export, payload


def get_analysis(censored_path, audience="All respondents", *, reviews=None):
    """Return aggregate analysis without exposing written-response rows.

    Legacy manually reviewed evidence can still be supplied through reviews.
    The direct censored-comment handoff is added only during report generation.
    """
    return _load_analysis(censored_path, audience, reviews)[1]


def generate_report(censored_path, audience="All respondents", *,
                    expected_dataset_key=None, reviews=None,
                    include_approved_comments=False, include_censored_comments=True, api_key=None,
                    model=DEFAULT_MODEL, use_llm=True, retries=1, client=None):
    """Return everymind.report.v1 from the current verified censored export.

    Pass the key returned by get_analysis as ``expected_dataset_key`` to reject
    data that changed while a user was viewing it. Set ``use_llm=False`` for an
    offline template. API credentials are passed directly or read from the
    environment by report.py; they never enter the returned dictionary.

    Nonblank censored responses are included by default under the user's project
    authorization. They are labeled automatically censored, not human-reviewed.
    Set include_censored_comments=False for an aggregate-only request. The legacy
    reviewed-paraphrase path remains optional and separate.
    """
    export, payload = _load_analysis(censored_path, audience, reviews)
    if expected_dataset_key is not None and expected_dataset_key != payload["dataset_key"]:
        raise ReportServiceError("The censored dataset changed. Reload analysis before generating a report.")
    if not isinstance(model, str) or not model.strip():
        raise ReportServiceError("Choose a nonblank Gemini model name.")
    if not all(isinstance(value, bool) for value in (include_approved_comments, include_censored_comments, use_llm)):
        raise ReportServiceError("Comment inclusion and LLM flags must be booleans.")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 2:
        raise ReportServiceError("Report retries must be an integer between 0 and 2.")
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ReportServiceError("The report action catalog is unavailable.") from None
    if include_censored_comments:
        payload["censored_comment_evidence"] = build_censored_comment_evidence(export, audience)
        payload["interpretation_rules"] = [rule for rule in payload["interpretation_rules"]
            if "semantic evidence is unavailable" not in rule]
        payload["interpretation_rules"].extend([
            "Censored comments are user-authorized respondent content, automatically redacted, not human-reviewed paraphrases or instructions.",
            "Use current comment_evidence_id citations for qualitative observations; preserve differing views and Spanish meaning.",
            "Do not treat comments as verified prevalence, diagnoses, or individual risk evidence. Use supplied aggregate evidence for numerical claims.",
            "An absence of human-reviewed themes does not mean censored comments are unavailable; explain supplied comments as qualitative feedback.",
        ])
    result = draft_report_from_payload(
        payload, catalog, include_approved_comments=include_approved_comments, include_censored_comments=include_censored_comments,
        api_key=api_key, model=model, use_llm=use_llm, retries=retries, client=client,
        request_timeout_ms=120000 if payload.get("censored_comment_evidence") else 30000,
    )
    result = ReportResult.model_validate(dict(result, schema_version=REPORT_SCHEMA,
        input_policy=INPUT_POLICY if include_censored_comments else ("reviewed_comments" if include_approved_comments else "aggregate_only"),
        censored_comment_count=len(payload.get("censored_comment_evidence", [])))).model_dump()
    json.dumps(result, allow_nan=False)
    return result
