import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean import load_export
from cleaned_analysis import build_ai_input
from comment_evidence import build_comment_evidence, prepare_review_packet

ROOT = Path(__file__).resolve().parents[1] / "examples"


def sample():
    key, responses, comments, _ = load_export((ROOT / "synthetic_survey.csv").read_bytes(), "sample.csv")
    reviews = json.loads((ROOT / "reviewed_comments.json").read_text())
    for review in reviews:
        if review["reviewer_status"] == "approved":
            review["privacy_screened"] = True
            review["approved_paraphrase_fingerprint"] = hashlib.sha256(review["approved_paraphrase"].encode()).hexdigest()
    return key, responses, comments, reviews


def test_approved_meaning_reaches_payload_without_source_identity():
    key, frame, comments, reviews = sample()
    # A raw-only identifying canary must never be copied into the payload.
    comments.loc[0, "original_text"] += " Alice PRIVATE_NAME_731 alice@example.com"
    reviews[0]["content_fingerprint"] = hashlib.sha256(comments.loc[0, "original_text"].encode()).hexdigest()
    lineage = {}
    payload = build_ai_input(frame, comments, key, "Students", reviews, lineage_out=lineage)
    assert len(payload["approved_comment_evidence"]) == 20
    text = json.dumps(payload)
    assert "PRIVATE_NAME_731" not in text and "alice@example.com" not in text
    assert "response_id" not in text and "SYN001" not in text
    assert "Add a practice call scenario." in text
    assert set(lineage) == {r["comment_evidence_id"] for r in payload["approved_comment_evidence"]}
    assert any(r["response_id"] == "SYN001" for r in lineage.values())


def test_changed_paraphrase_or_unapproved_privacy_cannot_pass():
    key, frame, comments, reviews = sample()
    reviews[0]["approved_paraphrase"] += " edited without review"
    reviews[1]["privacy_screened"] = False
    evidence, _, _ = build_comment_evidence(frame, comments, reviews, key, "Students")
    assert len(evidence) == 18
    assert not any("edited without review" in r["approved_paraphrase"] for r in evidence)
    assert build_comment_evidence(frame, comments, None, key, "Students")[0] == []
    assert build_comment_evidence(frame, comments, reviews, key, "School staff")[0] == []


def test_current_content_and_sample_cap():
    key, frame, comments, reviews = sample()
    evidence, lineage, coverage = build_comment_evidence(frame, comments, reviews, key, "Students", max_per_field=2)
    assert len(evidence) == len(lineage) == 4
    assert all(c["truncated"] for c in coverage)
    comments.loc[0, "original_text"] += " changed"
    evidence, _, _ = build_comment_evidence(frame, comments, reviews, key, "Students")
    assert not any(r["source_field"] == "most_valuable" for r in evidence)  # remaining reviewed n is nine


def test_review_packet_starts_private_and_pending():
    _, _, comments, _ = sample()
    packet = prepare_review_packet(comments)
    assert len(packet) == 60
    assert all(r["reviewer_status"] == "pending" and not r["privacy_screened"] and r["approved_paraphrase"] is None for r in packet)
