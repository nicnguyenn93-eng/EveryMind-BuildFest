"""Rebuild synthetic K3 JSON/CSV records; never reads real survey data."""
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean import EXPORT_COLUMNS, load_export

ROOT = Path(__file__).resolve().parent


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build():
    rows = []
    for i in range(1, 31):
        roles = ["Student"] if i <= 10 else ["Community member"]
        if i == 1:
            roles.append("School staff")
        elif 11 <= i <= 18:
            roles = ["School staff"]
        rows.append(dict(
            id=f"SYN{i:03}", role=";".join(roles), county="Synthetic County",
            training_date="2026-11-01",
            q1_knowledge=2 if i <= 5 else 4, q2_knowledge=4,
            q3_knowledge=None if i == 30 else (2 if i <= 5 else 4),
            q4_knowledge=3 if i == 10 else (5 if i == 30 else 4),
            q5_knowledge=3, q6_knowledge=5,
            recommendation=0 if i == 1 else 8,
            intent=0 if i == 1 else (None if i == 2 else 7),
            most_valuable="Synthetic feedback: the explanation of 988 was clear.",
            how_can_we_improve=("Synthetic feedback: add a practice call scenario."
                                if i <= 10 else "Synthetic feedback: no suggested change."),
        ))
    csv_path = ROOT / "synthetic_survey.csv"
    labels = {1: "Strongly disagree", 2: "Disagree", 3: "Neither agree nor disagree", 4: "Agree", 5: "Strongly agree"}
    export_rows = []
    for row in rows:
        source = dict(row, start_time="2026-11-01T09:00:00", completion_time="2026-11-01T09:05:00",
                      language="English", presenter_engagement="Agree", presenter_knowledge="Strongly agree",
                      training_organization="Very agree" if row["id"] == "SYN030" else "Agree")
        source["role"] = source["role"].replace("School staff", "School staff member").replace("Community member", "Other (e.g., community member)") + ";"
        for field in [f"q{i}_knowledge" for i in range(1, 7)]:
            source[field] = labels.get(source[field])
        export_rows.append({header: source[key] for key, header in EXPORT_COLUMNS.items()})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPORT_COLUMNS.values()))
        writer.writeheader()
        writer.writerows(export_rows)
    key, normalized, _, import_audit = load_export(csv_path.read_bytes(), csv_path.name)
    responses = normalized.to_dict("records")
    comments = []
    for row in rows:
        response = next(r for r in responses if r["id"] == row["id"])
        for field in ("most_valuable", "how_can_we_improve"):
            approved = int(row["id"][3:]) <= 10
            comments.append(dict(
                private_record_key=f"{row['id']}:{field}", response_id=row["id"],
                source_field=field, role_membership=response["role_membership"], language="English",
                content_fingerprint=hashlib.sha256(row[field].encode("utf-8")).hexdigest(),
                reviewer_status="approved" if approved else "pending",
                approved_paraphrase=("The explanation of 988 was clear." if field == "most_valuable"
                                     else "Add a practice call scenario.") if approved else None,
                theme_ids=(["THEME_CLARITY"] if field == "most_valuable" else ["THEME_SCENARIOS"]) if approved else [],
            ))
    evidence = []
    for audience, n, before, after in (("Students", 10, 5, 9), ("All respondents", 29, 24, 28)):
        for when, count in (("BEFORE", before), ("POST", after)):
            evidence.append(dict(
                dataset_key=key, audience=audience,
                evidence_id=f"{audience.upper().replace(' ', '_')}_EXPLAIN_988_{when}",
                survey_question=f"Explain 988: {'recalled before' if when == 'BEFORE' else 'post-training'} agreement",
                metric_type="paired_agreement", numerator_or_score_sum=count,
                valid_denominator=n, audience_total=10 if audience == "Students" else 30,
                unit="percent", display_value=f"{100 * count / n:.1f}%",
                caveat="Retrospective self-report; limited sample (10-29 valid pairs)."))
    report = dict(dataset_key=key, audience="Students", mode="template",
                  summary_blocks=["In this synthetic fixture, agreement on explaining 988 increased from 5/10 (50.0%) to 9/10 (90.0%) among paired student responses, a 40.0 percentage-point change."],
                  evidence_ids=[e["evidence_id"] for e in evidence if e["audience"] == "Students"],
                  proposed_action_id="ACT_PILOT_ROLEPLAY", staff_owner="Training Lead",
                  follow_up_measure="At the next two comparable sessions, record the proportion completing the practice-call checklist.",
                  limitations="Synthetic example only. Retrospective self-report, not causal evidence. Ten reviewed student improvement comments request scenarios; limited sample.")
    save("normalized_responses.json", responses)
    save("reviewed_comments.json", comments)
    save("evidence.json", evidence)
    save("report.json", report)
    (ROOT.parent / "schema.json").write_text(json.dumps(dict(
        contract_version="k3-v2", description="Export-compatible synthetic example records, not a JSON Schema validator. See examples/README.md.",
        evidence_row_schema=evidence[0], reviewed_comment_schema=comments[0],
        report_schema=report), indent=2) + "\n", encoding="utf-8")
    save("audit.json", dict(import_audit,
                            audience_totals={"Students": 10, "School staff": 9, "Known non-students": 20},
                            valid_intent=29, zero_intent=1, missing_intent=1,
                            comment_records=60, reviewed_records=20, pending_records=40))
    save("theme_summary.json", [dict(dataset_key=key, audience=audience,
         source_field="how_can_we_improve", theme_id="THEME_SCENARIOS",
         eligible_nonblank=total, reviewed_denominator=10, theme_positive=10,
         caveat="Synthetic reviewed sample; ten students selected by fixed SYN001-SYN010 ID range. Not a population prevalence estimate.")
         for audience, total in (("Students", 10), ("All respondents", 30))])
    save("privacy_expectations.json", dict(
        school_staff=dict(status="suppressed", evidence=[], search_results=[], theme_counts=[]),
        rules=["Require at least 10 valid respondents per statistic.",
               "Label 10-29 valid respondents limited.",
               "Withhold School staff figures and paraphrases (nine members).",
               "Withhold complementary releases that reveal a suppressed result; use one dimension at a time."] ))
    save("workbook_rows.json", [list(EXPORT_COLUMNS.values())] + [list(r.values()) for r in export_rows])
    return rows


if __name__ == "__main__":
    build()
