"""John's cleaner -> analysis -> aggregate-only AI input. No provider call."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

from analysis import analyze_data, AUDIENCES
from feedback import explore_feedback

ROOT = Path(__file__).resolve().parent


def adapt_cleaned(data, private):
    """Map John's contract; never copy source text into structural responses."""
    mapping = {"response_id": "id", "identify_before": "q1_knowledge", "identify_after": "q2_knowledge",
        "describe_before": "q3_knowledge", "describe_after": "q4_knowledge", "when_before": "q5_knowledge",
        "when_after": "q6_knowledge", "recommend": "recommendation", "call_intent": "intent"}
    responses = pd.DataFrame(index=data.index)
    for source, target in mapping.items():
        if source in data:
            responses[target] = data[source]
            if source + "__status" in data:
                responses[target + "_status"] = data[source + "__status"]
    if "id" not in responses:
        raise ValueError("John's cleaned data needs response_id.")
    responses["id"] = responses.id.astype(str)
    flags = [("role_student", "Student"), ("role_staff", "School staff"),
             ("role_caregiver", "Caregiver/parent"), ("role_other", "Community member")]
    if not all(c in data for c, _ in flags):
        raise ValueError("John's cleaned role flags are required.")
    responses["role_membership"] = data.apply(lambda row: [label for col, label in flags
        if pd.notna(row[col]) and bool(row[col]) and (label == "Student" or row.get("role__status") == "valid")], axis=1)
    private = pd.DataFrame(private)
    if not private.empty and ("response_id" not in private or private.response_id.astype(str).duplicated().any()):
        raise ValueError("Private comment IDs must be present and unique.")
    private_by_id = {str(r["response_id"]): r for r in private.to_dict("records")}
    comments = []
    for row in data.to_dict("records"):
        source = private_by_id.get(str(row["response_id"]), {})
        for raw_field, field in [("most_valuable", "most_valuable"), ("improve", "how_can_we_improve")]:
            if raw_field + "__category" not in row:
                continue
            if raw_field not in source:
                raise ValueError("Current private originals are needed for exploratory keyword analysis.")
            text = source[raw_field]
            text = text if isinstance(text, str) else ""
            comments.append(dict(response_id=str(row["response_id"]), source_field=field,
                original_text=text, response_category=row[raw_field + "__category"],
                language=row.get(raw_field + "__lang", "unknown"),
                content_fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest()))
    return responses, pd.DataFrame(comments)


def build_ai_input(responses, comments, dataset_key, audience="All respondents", reviews=None):
    """Construct payload only from privacy-checked aggregate functions."""
    analysis = analyze_data(responses, dataset_key, audience, comments, reviews)
    exploratory = explore_feedback(responses, comments, dataset_key, audience)
    return dict(schema_version="everymind.analysis.v1", dataset_key=dataset_key, audience=audience,
        status=analysis["status"], quantitative_evidence=analysis["quantitative_evidence"],
        qualitative_themes=analysis["qualitative_themes"], exploratory_feedback=exploratory,
        coverage=analysis["coverage"], limitations=analysis["limitations"],
        interpretation_rules=["Use quantitative evidence and approved qualitative themes as descriptive evidence only.",
            "Exploratory keyword matches and classifications are unreviewed; explicitly label them as such.",
            "Do not treat exploratory counts as verified prevalence or as support for an eligible recommendation.",
            "Do not invent counts, causes, correlations, statistical significance, or trends over time.",
            "Treat withheld, absent, and unavailable results as unknown, never zero.",
            "Return analysis only; no recommended actions or pilots are requested."])


def run(input_path, audience="All respondents", reviews=None):
    sys.path.insert(0, str(ROOT / "everymind_cleaning"))
    import everymind_clean as ec
    base = ROOT / "everymind_cleaning"
    result = ec.run_pipeline(input_path, base / "schema.json", base / "mapping_registry.json")
    if not result.checks["pass"].all():
        raise ValueError("Cleaning validation failed; inspect locally before releasing analysis.")
    responses, comments = adapt_cleaned(result.data, result.private)
    key = "john-clean:" + result.audit.dataset_key
    payload = build_ai_input(responses, comments, key, audience, reviews)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original workbook/CSV passed through John's cleaner locally")
    parser.add_argument("--audience", choices=sorted(AUDIENCES), default="All respondents")
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output", type=Path, help="Write aggregate JSON here; no external AI call is made")
    args = parser.parse_args()
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else None
    payload = run(args.input, args.audience, reviews)
    text = json.dumps(payload, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Aggregate AI input saved to {args.output}")
    else:
        print(text)
