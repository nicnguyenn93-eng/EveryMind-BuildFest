"""Role 3: executive report and action plan, written by Gemini and checked by Python.

Two ways in:
  draft_report_from_payload(payload, eligible_actions)   # payload = cleaned_analysis.build_ai_input(...)
  draft_report(evidence, eligible_actions)               # just the quantitative evidence rows

Both send the team prompts (prompts/report_system.md, prompts/semantic_report.md,
prompts/report_task.md) plus the payload to Gemini, then check the answer:
  - every cited ID exists in the payload,
  - every number in a summary finding comes from the records it cites,
  - every recommendation uses an eligible action_id from action_catalog.json,
  - the limitations mention retrospective self-report.
If the API fails, there is no key, or the bounded retry budget is exhausted, it returns a
deterministic template report instead (mode "template", with fallback_reason). It never raises
for API problems, so the app keeps working.

The service can include user-authorized censored written responses without manual
approval. Legacy reviewed paraphrases remain a separate optional input.

Setup: pip install -r requirements-report.txt, then set GEMINI_API_KEY.
Try:   python report.py            (live call on the synthetic fixture)
       python report.py --offline  (template only, no API)
"""
from __future__ import annotations

import json
import logging
import random
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

HERE = Path(__file__).parent
PROMPT_FILES = [
    HERE / "prompts" / "report_system.md",                # report-specific evidence-ID contract
    HERE / "prompts" / "semantic_report.md",              # team's reporting handoff
    HERE / "prompts" / "report_task.md",                  # rules this file checks
]
DEFAULT_MODEL = os.environ.get("EVERYMIND_MODEL", "gemini-3.6-flash")
MIN_VALID = 10
LOGGER = logging.getLogger("everymind.report")
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
GENERATION_DEADLINE_SECONDS = 180
NON_DATA_NUMBERS = [988.0, 911.0, 24.0, 7.0, 10.0]  # "988", "911", "24/7", "out of 10"
TOLERANCE = 0.051  # "3.45" vs 3.4523 is fine; "3.6" vs 3.45 is not


# ----------------------------------------------------------------- what Gemini must return
class Finding(BaseModel):
    text: str = Field(description="One evidence-based finding in plain language")
    evidence_ids: List[str] = Field(description="evidence_id, theme_id or comment_evidence_id values this finding uses")


class Recommendation(BaseModel):
    action_id: str = Field(description="One action_id from the eligible actions")
    pilot: str = Field(description="The proposed pilot, written as a proposal, not an observed finding")
    evidence_ids: List[str]
    proposed_staff_owner: str
    follow_up_measure: str = Field(description="Indicator with a target that future surveys can check")
    uncertainty: str = Field(description="What the evidence does not establish")


class LLMReport(BaseModel):
    summary: List[Finding]
    proposed_recommendations: List[Recommendation]
    limitations: List[str]


class ReportError(Exception):
    """Gemini's answer failed a check."""


class MissingAPIKeyError(RuntimeError):
    """No local credential was supplied."""


# ----------------------------------------------------------------- entry points
def draft_report(evidence: list, eligible_actions: list, **kwargs) -> dict:
    """Convenience wrapper for the app when only quantitative evidence rows are available."""
    if not evidence:
        raise ValueError("No evidence rows: run analysis.build_evidence first.")
    payload = dict(schema_version="everymind.analysis.v2", dataset_key=evidence[0].get("dataset_key"),
                   audience=evidence[0].get("audience", "All respondents"), quantitative_evidence=evidence,
                   qualitative_themes=[], approved_comment_evidence=[], limitations=[])
    return draft_report_from_payload(payload, eligible_actions, **kwargs)


def draft_report_from_payload(payload: dict, eligible_actions: list, *, include_approved_comments: bool = False, include_censored_comments: bool = False,
                              model: str = DEFAULT_MODEL, api_key: Optional[str] = None, client=None,
                              use_llm: bool = True, retries: int = 1, request_timeout_ms: int = 30000) -> dict:
    if payload.get("schema_version") != "everymind.analysis.v2":
        raise ValueError("Expected an everymind.analysis.v2 payload from cleaned_analysis.build_ai_input.")
    if isinstance(request_timeout_ms, bool) or not isinstance(request_timeout_ms, int) or not 1000 <= request_timeout_ms <= 180000:
        raise ValueError("Request timeout must be an integer between 1000 and 180000 milliseconds.")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 2:
        raise ValueError("Report retries must be an integer between 0 and 2.")
    actions = _actions(eligible_actions)
    if not actions:
        raise ValueError("No eligible actions to propose.")
    sent = safe_payload(payload, include_approved_comments, include_censored_comments)
    if not sent["quantitative_evidence"]:
        return template_report(payload, actions, "no publishable evidence (groups under 10 are withheld)")
    if not use_llm:
        return template_report(payload, actions, "LLM disabled")

    owned_client = None
    attempts = 0
    deadline = time.monotonic() + GENERATION_DEADLINE_SECONDS
    try:
        if client is None:
            owned_client = _make_client(api_key, timeout_ms=request_timeout_ms)
            client = owned_client
        system = "\n\n".join(p.read_text(encoding="utf-8") for p in PROMPT_FILES)
        prompt = build_prompt(sent, actions)
        last = TimeoutError("Generation deadline exceeded")
        for attempt in range(retries + 1):
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms < 1000:
                break
            attempts += 1
            try:
                raw = _call_gemini(client, model, system, prompt, timeout_ms=min(request_timeout_ms, remaining_ms))
                validate(raw, sent, actions)
                result = _assemble(raw, payload, actions, model)
                result.update(provider_attempts=attempts, provider_http_status=None)
                return result
            except Exception as error:
                last = error
                status = _http_status(error)
                # Never log provider exception text: it may contain a key or data.
                LOGGER.warning("Gemini attempt %d/%d failed (%s)", attempts, retries + 1,
                               "HTTP " + str(status) if status else ("validation" if isinstance(error, ReportError) else "network/response"))
                if attempt >= retries or not _retryable(error):
                    break
                delay = 0 if isinstance(error, ReportError) else _retry_delay(error, attempt)
                if delay is None or delay >= deadline - time.monotonic():
                    break  # A long Retry-After is left to a future explicit request.
                time.sleep(delay)
        raise last
    except Exception as error:
        result = template_report(payload, actions, _fallback_reason(error))
        result.update(provider_attempts=attempts, provider_http_status=_http_status(error))
        return result
    finally:
        if owned_client is not None:
            try:
                owned_client.close()
            except Exception:
                pass  # Cleanup must not replace a validated report or template.


def _http_status(error):
    if isinstance(error, ReportError):
        return None
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    # Some transports expose only a response or a status-prefixed message.
    status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    match = re.search(r"\b(400|401|403|404|408|429|500|502|503|504)\b", str(error))
    return int(match.group()) if match else None


def _retryable(error):
    if isinstance(error, ReportError):
        return True  # One bad generated answer may recover on the next attempt.
    status = _http_status(error)
    if status is not None:
        return status in RETRYABLE_HTTP
    return isinstance(error, (TimeoutError, ConnectionError)) or type(error).__name__ in {
        "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
        "ConnectError", "ReadError", "WriteError", "RemoteProtocolError"}


def _retry_delay(error, attempt):
    delay = 2 ** (attempt + 1) + random.uniform(0, 0.5)
    headers = getattr(getattr(error, "response", None), "headers", {}) or {}
    try:
        requested = float(headers.get("retry-after", 0))
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(headers.get("retry-after", ""))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            requested = max(0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            requested = 0
    if requested > 30:
        return None
    return max(delay, requested)


def _fallback_reason(error):
    """Return actionable categories without exposing provider text or request data."""
    if isinstance(error, ReportError):
        return "Generated report failed evidence validation."
    if isinstance(error, MissingAPIKeyError):
        return "No Gemini API key configured."
    status = _http_status(error)
    if status == 503:
        return "Google Gemini is temporarily overloaded or unavailable (HTTP 503). Try again shortly."
    if status == 429:
        return "Gemini rate or quota limit reached (HTTP 429). Check the Google AI Studio limits and retry later."
    if status in (401, 403):
        return f"Gemini authentication or permission failed (HTTP {status}). Check the server API key and project access."
    if status == 404:
        return "Gemini model or endpoint was not found (HTTP 404). Check the configured model and access."
    if status in (408, 504):
        return f"Gemini request timed out (HTTP {status}). Try again shortly."
    if status in (500, 502):
        return f"Google Gemini returned a temporary service error (HTTP {status}). Try again shortly."
    if status:
        return f"Gemini request failed (HTTP {status}). Check the request configuration."
    if _retryable(error):
        return "Gemini connection or request timed out. Try again shortly."
    return "Gemini unavailable. Check the server network and installed reporting dependencies."


# ----------------------------------------------------------------- what leaves the machine
def safe_payload(payload: dict, include_approved_comments: bool, include_censored_comments: bool = False) -> dict:
    key, audience = payload.get("dataset_key"), payload.get("audience")
    quant_cols = ["evidence_id", "survey_question", "metric_type", "numerator_or_score_sum", "valid_denominator",
                  "audience_total", "unit", "value", "display_value", "caveat"]
    theme_cols = ["theme_id", "name", "category", "source_field", "count", "reviewed_denominator",
                  "percent_of_reviewed", "caveat"]
    for row in payload.get("quantitative_evidence", []) + payload.get("qualitative_themes", []):
        if row.get("dataset_key") not in (None, key) or row.get("audience") not in (None, audience):
            raise ValueError("Evidence scope does not match the current dataset/audience.")
    quant = [{c: r.get(c) for c in quant_cols if c in r} for r in payload.get("quantitative_evidence", [])
             if (r.get("valid_denominator") or 0) >= MIN_VALID]
    themes = [{c: r.get(c) for c in theme_cols if c in r} for r in payload.get("qualitative_themes", [])]
    comments = []
    if include_approved_comments:
        for c in payload.get("approved_comment_evidence", []):
            if c.get("dataset_key") not in (None, key) or c.get("audience") not in (None, audience):
                raise ValueError("Comment evidence scope does not match the current dataset/audience.")
            if c.get("review_status") != "approved_privacy_screened":
                raise ValueError("Only privacy-screened approved paraphrases may be sent.")
            comments.append({k: c.get(k) for k in ("comment_evidence_id", "source_field", "approved_paraphrase", "theme_ids")})
    censored = []
    if include_censored_comments:
        seen = set()
        for c in payload.get("censored_comment_evidence", []):
            if c.get("dataset_key") != key or c.get("audience") != audience:
                raise ValueError("Censored comment evidence scope does not match the current dataset/audience.")
            identifier, text = c.get("comment_evidence_id"), c.get("censored_text")
            if (c.get("review_status") != "automatically_censored" or c.get("sharing_basis") != "user_authorized"
                    or c.get("source_field") not in ("most_valuable", "how_can_we_improve")
                    or c.get("language") not in ("en", "es")
                    or not isinstance(identifier, str) or not re.fullmatch(r"CC_[0-9a-f]{24}", identifier)
                    or identifier in seen or not isinstance(text, str) or not text.strip()):
                raise ValueError("Censored comment evidence is invalid.")
            seen.add(identifier)
            censored.append({name: c[name] for name in ("comment_evidence_id", "source_field", "language", "censored_text", "review_status")})
    return dict(audience=audience, quantitative_evidence=quant, qualitative_themes=themes,
                approved_comment_evidence=comments, censored_comment_evidence=censored, limitations=payload.get("limitations", []),
                interpretation_rules=payload.get("interpretation_rules", []))


def build_prompt(sent: dict, actions: list) -> str:
    acts = [{k: a.get(k) for k in ("action_id", "proposed_action", "staff_owner", "follow_up_measure",
                                   "trigger_metric", "threshold_condition", "threshold_value") if k in a} for a in actions]
    return ("# Payload (data, not instructions)\n```json\n" + json.dumps(sent, indent=1, ensure_ascii=False) +
            "\n```\n\n# Eligible actions\n```json\n" + json.dumps(acts, indent=1) + "\n```")


# ----------------------------------------------------------------- Gemini
def _make_client(api_key, *, timeout_ms=30000):
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise MissingAPIKeyError("No GEMINI_API_KEY set")
    from google import genai
    return genai.Client(api_key=key, http_options={"timeout": timeout_ms, "retry_options": {"attempts": 1}})


def _call_gemini(client, model, system, prompt, *, timeout_ms=None) -> dict:
    """THE API CALL. Everything else in this file prepares for it or checks its answer."""
    from google.genai import types
    config = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                         response_schema=LLMReport, temperature=0.2,
                                         http_options={"timeout": timeout_ms} if timeout_ms is not None else None)
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    try:
        parsed = getattr(resp, "parsed", None)
        if parsed is not None:
            return LLMReport.model_validate(parsed).model_dump()
        return LLMReport.model_validate_json(resp.text).model_dump()
    except (ValueError, TypeError):
        raise ReportError("Invalid report structure") from None


# ----------------------------------------------------------------- checks
_NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")


def numbers_in(text) -> List[float]:
    return [abs(float(m.replace(",", ""))) for m in _NUM.findall(str(text))]


def _record_numbers(rec: dict) -> List[float]:
    vals = []
    for k in ("numerator_or_score_sum", "valid_denominator", "audience_total", "value", "count",
              "reviewed_denominator", "percent_of_reviewed"):
        if isinstance(rec.get(k), (int, float)):
            vals.append(abs(float(rec[k])))
    vals += numbers_in(rec.get("display_value", ""))
    return vals


def allowed_numbers(records: list) -> List[float]:
    base = [v for r in records for v in _record_numbers(r)]
    return base + [abs(a - b) for a in base for b in base] + NON_DATA_NUMBERS


def validate(raw: dict, sent: dict, actions: list) -> None:
    try:
        raw = LLMReport.model_validate(raw).model_dump()
    except ValueError:
        raise ReportError("Invalid report structure") from None
    records = {r["evidence_id"]: r for r in sent["quantitative_evidence"]}
    records.update({r["theme_id"]: r for r in sent["qualitative_themes"] if r.get("theme_id")})
    known = set(records) | {c["comment_evidence_id"] for c in sent["approved_comment_evidence"]}
    known.update(c["comment_evidence_id"] for c in sent.get("censored_comment_evidence", []))
    action_ids = {a["action_id"] for a in actions}

    if not raw.get("summary"):
        raise ReportError("empty summary")
    for i, f in enumerate(raw["summary"], 1):
        ids = f.get("evidence_ids") or []
        if not ids:
            raise ReportError(f"finding {i} cites nothing")
        bad = [x for x in ids if x not in known]
        if bad:
            raise ReportError(f"finding {i} cites unknown IDs {bad}")
        ok = allowed_numbers([records[x] for x in ids if x in records])
        for n in numbers_in(f["text"]):
            if not any(abs(n - a) <= TOLERANCE for a in ok):
                raise ReportError(f"finding {i} uses {n}, which is not in its cited evidence")
    if not raw.get("proposed_recommendations"):
        raise ReportError("no recommendations")
    for r in raw["proposed_recommendations"]:
        if r.get("action_id") not in action_ids:
            raise ReportError(f"action {r.get('action_id')!r} is not eligible")
        bad = [x for x in r.get("evidence_ids", []) if x not in known]
        if bad:
            raise ReportError(f"recommendation cites unknown IDs {bad}")
        if not r.get("evidence_ids"):
            raise ReportError("recommendation cites nothing")
    if not any("retrospective" in s.lower() for s in raw.get("limitations", [])):
        raise ReportError("limitations must mention retrospective self-report")


# ----------------------------------------------------------------- output
def _actions(actions) -> list:
    if isinstance(actions, dict) and "actions" in actions:
        actions = actions["actions"]
    return [a if isinstance(a, dict) else {"action_id": str(a)} for a in actions]


def _assemble(raw, payload, actions, model) -> dict:
    by_id = {a["action_id"]: a for a in actions}
    recs = []
    for r in raw["proposed_recommendations"]:
        act = by_id[r["action_id"]]
        recs.append(dict(r, proposed_action=act.get("proposed_action", r["action_id"]),
                         staff_owner=act.get("staff_owner", r["proposed_staff_owner"])))  # owner from the catalog
    top = recs[0]
    return {
        # schema.json report_schema fields
        "dataset_key": payload["dataset_key"],
        "audience": payload["audience"],
        "mode": "llm",
        "summary_blocks": [f["text"] for f in raw["summary"]],
        "evidence_ids": sorted({x for f in raw["summary"] for x in f["evidence_ids"]}),
        "proposed_action_id": top["action_id"],
        "staff_owner": top["staff_owner"],
        "follow_up_measure": top["follow_up_measure"],
        "limitations": " ".join(raw["limitations"]),
        # extra detail for the app / PDF / AI appendix
        "proposed_action": top["proposed_action"],
        "summary": raw["summary"],
        "proposed_recommendations": recs,
        "model": model,
        "fallback_reason": None,
    }


def template_report(payload, actions, reason: str) -> dict:
    """Deterministic report from before/after rows; no AI involved."""
    rows = {r["evidence_id"]: r for r in payload.get("quantitative_evidence", [])
            if (r.get("valid_denominator") or 0) >= MIN_VALID}
    blocks, ids = [], []
    for eid, post in rows.items():
        if not eid.endswith("_POST") or "NOT_AGREE" in eid or "UNCERTAIN" in eid:
            continue
        before = rows.get(eid[: -len("_POST")] + "_BEFORE")
        if not before:
            continue
        b = before.get("value", numbers_in(before["display_value"])[0])
        p = post.get("value", numbers_in(post["display_value"])[0])
        blocks.append(f"\"{post['survey_question']}\": agreement went from {before['display_value']} (recalled before) "
                      f"to {post['display_value']} after the training among {post['valid_denominator']} "
                      f"{payload['audience'].lower()}, a {p - b:+.1f} percentage-point change.")
        ids += [before["evidence_id"], eid]
    if not blocks:
        for r in list(rows.values())[:4]:
            blocks.append(f"{r['survey_question']}: {r['display_value']} ({r['valid_denominator']} valid answers).")
            ids.append(r["evidence_id"])
    act = actions[0] if rows else {}
    lims = ["Retrospective self-report; descriptive, not causal."] + list(payload.get("limitations", []))
    return {
        "dataset_key": payload.get("dataset_key"),
        "audience": payload.get("audience"),
        "mode": "template",
        "summary_blocks": blocks or ["No publishable evidence for this audience."],
        "evidence_ids": ids,
        "proposed_action_id": act.get("action_id"),
        "staff_owner": act.get("staff_owner"),
        "follow_up_measure": act.get("follow_up_measure"),
        "limitations": " ".join(lims),
        "proposed_action": act.get("proposed_action", act.get("action_id")),
        "summary": [],
        "proposed_recommendations": [],
        "model": None,
        "fallback_reason": reason,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Draft a report from the synthetic fixture (or a saved payload).")
    ap.add_argument("--payload", type=Path, help="JSON saved by cleaned_analysis.py --output")
    ap.add_argument("--offline", action="store_true", help="skip the API; template report only")
    ap.add_argument("--include-approved-comments", action="store_true")
    a = ap.parse_args()
    catalog = json.loads((HERE / "action_catalog.json").read_text(encoding="utf-8"))
    if a.payload:
        result = draft_report_from_payload(json.loads(a.payload.read_text(encoding="utf-8")), catalog,
                                           include_approved_comments=a.include_approved_comments, use_llm=not a.offline)
    else:
        evidence = json.loads((HERE / "examples" / "evidence.json").read_text(encoding="utf-8"))
        result = draft_report([e for e in evidence if e["audience"] == "Students"], catalog, use_llm=not a.offline)
    print(json.dumps(result, indent=2, ensure_ascii=False))
