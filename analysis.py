"""Descriptive analysis of John's normalized responses. No recommendations or AI calls."""
import json

import pandas as pd

MIN_VALID = 10
PAIRS = [("identify_challenges", "q1_knowledge", "q2_knowledge", "Identify mental health challenges and crises"),
         ("explain_988", "q3_knowledge", "q4_knowledge", "Describe 988 and how it works"),
         ("when_988", "q5_knowledge", "q6_knowledge", "Know when to use 988")]
AUDIENCES = {"All respondents", "Students", "Known non-students", "School staff", "Caregiver/parent", "Community member"}


def validate_responses(responses):
    """Reject ambiguous structural input rather than silently analyzing everyone."""
    frame = pd.DataFrame(responses).copy()
    if not {"id", "role_membership"}.issubset(frame.columns):
        raise ValueError("Analysis requires id and role_membership columns from clean.load_export.")
    if frame.id.isna().any() or frame.id.astype(str).str.strip().eq("").any() or frame.id.astype(str).duplicated().any():
        raise ValueError("Response IDs must be present and unique.")
    if not frame.role_membership.map(lambda roles: isinstance(roles, list) and all(isinstance(r, str) and r.strip() for r in roles)).all():
        raise ValueError("role_membership must contain lists of nonblank role strings.")
    frame["id"] = frame.id.astype(str)
    return frame


def audience_mask(frame, audience):
    if audience not in AUDIENCES:
        raise ValueError(f"Unsupported audience: {audience}")
    if audience == "All respondents":
        return pd.Series(True, index=frame.index)
    if audience == "Known non-students":
        known = {"School staff", "Caregiver/parent", "Community member"}
        return frame.role_membership.map(lambda roles: bool(set(roles) & known) and "Student" not in roles)
    role = "Student" if audience == "Students" else audience
    return frame.role_membership.map(lambda roles: role in roles)


def scores(frame, field, low=1, high=5):
    if field not in frame:
        return pd.Series(float("nan"), index=frame.index)
    values = pd.to_numeric(frame[field], errors="coerce")
    valid = values.between(low, high) & values.mod(1).eq(0)
    if f"{field}_status" in frame:
        valid &= frame[f"{field}_status"].eq("valid")
    return values.where(valid)


def publishable(valid, selected):
    """Require 10 valid people and protect a small valid complement."""
    n = int((valid & selected).sum())
    complement = int((valid & ~selected).sum())
    return n >= MIN_VALID and not 0 < complement < MIN_VALID


def build_evidence(responses, audience="All respondents", dataset_key=None):
    """Return only permitted evidence rows, calculated with unrounded inputs."""
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    if not publishable(pd.Series(True, index=frame.index), selected):
        return []
    if not dataset_key:
        raise ValueError("Pass the current dataset_key returned by clean.load_export.")
    total = int(selected.sum())
    prefix = audience.upper().replace(" ", "_").replace("/", "_")
    evidence = []

    def append(identifier, question, kind, numerator, n, unit, value, extra="", **details):
        caveat = "Retrospective self-report; descriptive, not causal."
        if n < 30:
            caveat += " Limited sample (10-29 valid respondents)."
        if extra:
            caveat += " " + extra
        evidence.append(dict(dataset_key=dataset_key, audience=audience,
            evidence_id=f"{prefix}_{identifier.upper()}", survey_question=question,
            metric_type=kind, numerator_or_score_sum=float(numerator), valid_denominator=n,
            audience_total=total, unit=unit, value=float(value),
            display_value=f"{value:.1f}%" if unit == "percent" else (f"{value:+.1f} pp" if unit == "percentage_points" else f"{value:.2f}"),
            caveat=caveat, **details))

    for slug, before, after, question in PAIRS:
        pre, post = scores(frame, before), scores(frame, after)
        valid = pre.notna() & post.notna()
        if not publishable(valid, selected):
            continue
        paired = valid & selected
        n = int(paired.sum())
        b, a = int(pre[paired].ge(4).sum()), int(post[paired].ge(4).sum())
        for suffix, count in [("before", b), ("post", a)]:
            append(f"{slug}_{suffix}", question, "paired_agreement", count, n, "percent", 100 * count / n)
        append(f"{slug}_change", question, "paired_agreement_change", a-b, n,
               "percentage_points", 100 * (a/n-b/n), before_agree=b, post_agree=a)
    for field in ["recommendation", "intent"]:
        values = scores(frame, field, 0, 10)
        valid = values.notna()
        if not publishable(valid, selected):
            continue
        subset = values[valid & selected]
        n, score_sum = len(subset), float(subset.sum())
        append(f"{field}_mean", field, "mean", score_sum, n, "score_0_10", score_sum/n,
               "Intent is stated likelihood, not observed behavior." if field == "intent" else "")
        # Coverage is an item statistic: do not bypass its valid-n suppression.
        append(f"{field}_coverage", field, "answer_coverage", n, total, "percent", 100*n/total)
        counts = subset.value_counts().sort_index()
        if all(int(c) >= MIN_VALID and not 0 < n-int(c) < MIN_VALID for c in counts):
            for score, count in counts.items():
                append(f"{field}_score_{int(score)}", field, "score_distribution", count, n, "percent", 100*count/n, score=int(score))
    post_explain, post_when = scores(frame, "q4_knowledge"), scores(frame, "q6_knowledge")
    valid = post_explain.notna() & post_when.notna()
    if publishable(valid, selected):
        n = int((valid & selected).sum())
        count = int(((post_explain.eq(3) | post_when.eq(3)) & valid & selected).sum())
        append("uncertain_988_post", "Neutral on either post-training 988 item", "neutral_on_either",
               count, n, "percent", 100*count/n, "Neutral means the scale midpoint; disagreement is separate.")
        not_agree = int(((post_explain.le(3) | post_when.le(3)) & valid & selected).sum())
        append("not_agree_988_post", "Below agreement on either post-training 988 item", "not_agree_on_either",
               not_agree, n, "percent", 100*not_agree/n,
               "Combines neutral and disagreement; distinct from neutral alone.")
    return evidence


def compare_audiences(responses, dataset_key, group="Students", comparator="Known non-students"):
    """Explicit descriptive differences between nonoverlapping valid groups."""
    frame = validate_responses(responses)
    if (audience_mask(frame, group) & audience_mask(frame, comparator)).any():
        raise ValueError("Comparisons require nonoverlapping groups.")
    left = build_evidence(frame, group, dataset_key)
    # Match by question/type, not audience-specific evidence identifiers.
    right = {(e["survey_question"], e["metric_type"]): e for e in build_evidence(frame, comparator, dataset_key)
             if e["metric_type"] in ("mean", "paired_agreement_change", "neutral_on_either")}
    comparisons = []
    for e in left:
        r = right.get((e["survey_question"], e["metric_type"]))
        if r is None:
            continue
        comparisons.append(dict(dataset_key=dataset_key, group=group, comparator=comparator,
            question=e["survey_question"], metric_type=e["metric_type"], group_value=e["value"],
            comparator_value=r["value"], difference=e["value"]-r["value"],
            unit="percentage_points" if e["unit"] == "percent" else e["unit"],
            group_valid_n=e["valid_denominator"], comparator_valid_n=r["valid_denominator"],
            evidence_ids=[e["evidence_id"], r["evidence_id"]],
            caveat="Descriptive difference; not statistical significance or a causal effect. " + e["caveat"] + " " + r["caveat"]))
    return comparisons


def analyze_data(responses, dataset_key, audience="All respondents", private_comments=None, reviews=None):
    """JSON-compatible analysis only. Raw comments and recommendations never appear."""
    from feedback import summarize_themes
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    allowed = publishable(pd.Series(True, index=frame.index), selected)
    evidence = build_evidence(frame, audience, dataset_key)
    themes = summarize_themes(frame, private_comments, reviews, dataset_key, audience)
    coverage = []
    if allowed:
        for field in [f"q{i}_knowledge" for i in range(1, 7)] + ["recommendation", "intent"]:
            values = scores(frame, field, 0 if field in ("recommendation", "intent") else 1,
                            10 if field in ("recommendation", "intent") else 5)
            released = field in frame and publishable(values.notna(), selected)
            coverage.append(dict(field=field, status="available" if released else ("absent" if field not in frame else "withheld"),
                valid_n=int((values.notna() & selected).sum()) if released else None,
                audience_total=int(selected.sum()) if released else None))
    return dict(dataset_key=dataset_key, audience=audience,
        status="available" if allowed else "withheld_or_empty",
        quantitative_evidence=evidence, qualitative_themes=themes["themes"],
        coverage=dict(quantitative=coverage, qualitative=themes["coverage"]),
        limitations=["Descriptive retrospective self-report; no causal effects, significance tests, or retention predictions.",
                     "Item denominators vary; paired knowledge calculations exclude invalid values on either side.",
                     "Only fingerprint-matched approved comments contribute to themes; reviewed samples need not represent all responses.",
                     "Small groups, small theme counts/complements, and detailed score distributions may be withheld.",
                     "Stateless outputs do not prevent disclosure by combining historical exports; the frontend must control releases."])


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from clean import load_export
    parser = argparse.ArgumentParser(description="Local descriptive survey analysis; outputs aggregates only.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--audience", default="All respondents", choices=sorted(AUDIENCES))
    parser.add_argument("--reviews", type=Path, help="Local approved-review JSON; originals are never printed.")
    args = parser.parse_args()
    key, responses, comments, _ = load_export(args.input.read_bytes(), args.input.name)
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else None
    print(json.dumps(analyze_data(responses, key, args.audience, comments, reviews), indent=2, allow_nan=False))
