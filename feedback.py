"""Local open-response coding suggestions and reviewed thematic analysis."""
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

CODEBOOK = json.loads(Path(__file__).with_name("codebook.json").read_text(encoding="utf-8"))
FIELDS = ("most_valuable", "how_can_we_improve")


def suggest_theme_codes(private_comments):
    """PRIVATE review aid. Keyword suggestions are not approved thematic findings."""
    suggestions = []
    for row in pd.DataFrame(private_comments).to_dict("records"):
        text = row.get("original_text")
        text = text if isinstance(text, str) else ""
        field = row.get("source_field")
        if field not in FIELDS:
            continue
        candidates = [theme["theme_id"] for theme in CODEBOOK if field in theme["source_fields"] and
                      any(re.search(pattern, text, re.IGNORECASE) for pattern in theme["patterns"])]
        suggestions.append(dict(response_id=str(row["response_id"]), source_field=field,
            content_fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            reviewer_status="pending", suggested_theme_ids=candidates,
            review_category="missing" if not text.strip() else "needs_review"))
    return suggestions


def summarize_themes(responses, private_comments, reviews, dataset_key, audience="All respondents"):
    """Count themes once per response/field, after identity and privacy checks.

    Approval asserts an operator checked meaning, identifiers, and paraphrase.
    Only current response ID + field + exact-content fingerprint can inherit it.
    No source text or paraphrases are released by this aggregate function.
    """
    from analysis import validate_responses, audience_mask, publishable, MIN_VALID
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    empty = dict(themes=[], coverage=[])
    if not publishable(pd.Series(True, index=frame.index), selected) or private_comments is None:
        return empty
    current = pd.DataFrame(private_comments).to_dict("records")
    review_records = [] if reviews is None else pd.DataFrame(reviews).to_dict("records")
    review_map = {}
    for r in review_records:
        identity = (str(r.get("response_id")), r.get("source_field"))
        if identity in review_map:
            raise ValueError("Duplicate review for a response/source field; resolve locally.")
        review_map[identity] = r
    memberships = dict(zip(frame.id, frame.role_membership))
    selected_ids = set(frame.loc[selected, "id"])
    seen = set()
    matched = {field: [] for field in FIELDS}
    known_themes = {t["theme_id"]: t for t in CODEBOOK}
    for row in current:
        response_id, field = str(row.get("response_id")), row.get("source_field")
        if response_id not in memberships or field not in FIELDS:
            continue
        identity = (response_id, field)
        if identity in seen:
            raise ValueError("Duplicate current comment for a response/source field.")
        seen.add(identity)
        original = row.get("original_text")
        original = original if isinstance(original, str) else ""
        nonblank = bool(original.strip())
        r = review_map.get(identity, {})
        themes = r.get("theme_ids", [])
        valid_themes = isinstance(themes, list) and all(isinstance(t, str) and t in known_themes and
                          field in known_themes[t]["source_fields"] for t in themes)
        if valid_themes and set(themes) & {"NO_SUGGESTED_CHANGE", "UNCLEAR"} and len(set(themes)) > 1:
            valid_themes = False
        approved = (nonblank and r.get("reviewer_status") == "approved" and
                    r.get("content_fingerprint") == hashlib.sha256(original.encode("utf-8")).hexdigest() and
                    isinstance(r.get("approved_paraphrase"), str) and bool(r["approved_paraphrase"].strip()) and valid_themes)
        matched[field].append(dict(response_id=response_id, selected=response_id in selected_ids,
                                   nonblank=nonblank, approved=approved, themes=set(themes) if approved else set()))
    output = dict(themes=[], coverage=[])
    for field, records in matched.items():
        local = [r for r in records if r["selected"]]
        if not records:
            output["coverage"].append(dict(source_field=field, status="absent"))
            continue
        eligible = sum(r["nonblank"] for r in local)
        reviewed = sum(r["approved"] for r in local)
        # Suppress an entire coverage breakdown if any positive cell/complement
        # is small. This prevents pending = eligible - reviewed disclosures.
        cells = [eligible, reviewed, eligible-reviewed, len(local)-eligible]
        other_reviewed = sum(r["approved"] for r in records if not r["selected"])
        coverage_allowed = all(c == 0 or c >= MIN_VALID for c in cells) and not 0 < other_reviewed < MIN_VALID
        output["coverage"].append(dict(source_field=field, status="available" if coverage_allowed else "withheld",
            eligible_nonblank=eligible if coverage_allowed else None,
            reviewed_denominator=reviewed if coverage_allowed else None,
            pending_nonblank=eligible-reviewed if coverage_allowed else None,
            missing=len(local)-eligible if coverage_allowed else None))
        if reviewed < MIN_VALID or not coverage_allowed:
            continue
        for theme_id, theme in known_themes.items():
            if field not in theme["source_fields"]:
                continue
            count = sum(r["approved"] and theme_id in r["themes"] for r in local)
            other_count = sum(r["approved"] and theme_id in r["themes"] for r in records if not r["selected"])
            if count < MIN_VALID or 0 < reviewed-count < MIN_VALID or 0 < other_count < MIN_VALID:
                continue
            output["themes"].append(dict(dataset_key=dataset_key, audience=audience,
                theme_id=theme_id, name=theme["name"], category=theme["category"], source_field=field,
                count=int(count), reviewed_denominator=reviewed, eligible_nonblank=eligible,
                percent_of_reviewed=100*count/reviewed,
                caveat="Reviewed comments only; multiple themes per response allowed. Not population prevalence." +
                       (" Limited reviewed sample (10-29)." if reviewed < 30 else "")))
    return output


def explore_feedback(responses, private_comments, dataset_key, audience="All respondents"):
    """Aggregate local classifications and UNREVIEWED English keyword matches.

    Private input rows need response_id, source_field, original_text,
    response_category and language. Only fixed codebook labels/counts leave here.
    """
    from analysis import validate_responses, audience_mask, publishable, MIN_VALID
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    if not publishable(pd.Series(True, index=frame.index), selected):
        return []
    local_ids = set(frame.loc[selected, "id"])
    ids = set(frame.id)
    records = pd.DataFrame(private_comments).to_dict("records") if private_comments is not None else []
    seen = set()
    for row in records:
        identity = (str(row.get("response_id")), row.get("source_field"))
        if identity in seen:
            raise ValueError("Duplicate exploratory comment record.")
        seen.add(identity)
    def safe(n, total):
        return (n == 0 or n >= MIN_VALID) and not 0 < total-n < MIN_VALID
    output = []
    for field in FIELDS:
        available = [r for r in records if r.get("source_field") == field and str(r.get("response_id")) in ids]
        local = [r for r in available if str(r["response_id"]) in local_ids]
        if not available:
            output.append(dict(source_field=field, status="absent"))
            continue
        categories = ("blank", "unclear", "none_stated", "substantive")
        counts = {c: sum(r.get("response_category") == c for r in local) for c in categories}
        category_allowed = (sum(counts.values()) == len(local) and
            all(safe(n, len(local)) for n in counts.values()) and
            all(not 0 < sum(r.get("response_category") == c and str(r["response_id"]) not in local_ids for r in available) < MIN_VALID for c in categories))
        # English-only patterns cannot estimate prevalence among other languages.
        eligible = [r for r in available if r.get("response_category") == "substantive" and r.get("language") in ("en", "English")]
        scanned = [r for r in eligible if str(r["response_id"]) in local_ids]
        complement_n = len(eligible)-len(scanned)
        release = len(scanned) >= MIN_VALID and not 0 < complement_n < MIN_VALID
        matches = []
        for theme in CODEBOOK:
            if field not in theme["source_fields"] or not theme["patterns"] or theme["category"] in ("No Suggested Change", "Unclear"):
                continue
            def matched(r):
                text = r.get("original_text")
                return isinstance(text, str) and any(re.search(p, text, re.IGNORECASE) for p in theme["patterns"])
            n = sum(matched(r) for r in scanned)
            other = sum(matched(r) for r in eligible if str(r["response_id"]) not in local_ids)
            if not release or n < MIN_VALID or not safe(n, len(scanned)) or 0 < other < MIN_VALID:
                continue
            matches.append(dict(theme_id=theme["theme_id"], name=theme["name"], count=n,
                scanned_denominator=len(scanned), review_status="unreviewed_keyword_match",
                percent_of_scanned=100*n/len(scanned)))
        output.append(dict(dataset_key=dataset_key, audience=audience, source_field=field,
            status="exploratory", classification_method="local_rule_based_unreviewed",
            categories=counts if category_allowed else None,
            categories_status="available" if category_allowed else "withheld",
            scanned_denominator=len(scanned) if release else None,
            keyword_matches=matches,
            limitations=["English keyword matches in substantive responses only; other languages are not analyzed by these patterns.",
                         "Negation, context, synonyms and sarcasm can cause errors; no match is not evidence of no theme.",
                         "These are unreviewed exploratory signals, not verified themes, prevalence, causes, or action eligibility.",
                         "Small positive counts and complements are withheld; withheld is not zero."]))
    return output
