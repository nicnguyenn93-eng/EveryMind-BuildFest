"""Export-shaped import regression tests using invented records only."""
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean import EXPORT_COLUMNS, load_export

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_survey.csv"


def encode(frame):
    return frame.to_csv(index=False).encode("utf-8")


def test_reordered_case_space_headers_and_optional_absence():
    frame = pd.read_csv(FIXTURE)
    key, expected, _, _ = load_export(encode(frame), "a.csv")
    reordered = frame.iloc[:, ::-1].copy()
    reordered.columns = ["  " + c.upper().replace(" ", "\u00a0 ") + "  " for c in reordered.columns]
    new_key, actual, _, _ = load_export(encode(reordered), "b.CSV")
    assert new_key == key
    pd.testing.assert_frame_equal(expected, actual)
    frame = frame.drop(columns=[EXPORT_COLUMNS["intent"]])
    _, actual, _, audit = load_export(encode(frame), "a.csv")
    assert "intent" not in actual and not audit["has_optional_intent"]
    assert "q4_knowledge" in actual


def test_required_column_duplicates_and_unsupported_file_rejected():
    frame = pd.read_csv(FIXTURE)
    with pytest.raises(ValueError, match="q3_knowledge"):
        load_export(encode(frame.drop(columns=[EXPORT_COLUMNS["q3_knowledge"]])), "a.csv")
    with pytest.raises(ValueError, match="Duplicate response IDs"):
        load_export(encode(pd.concat([frame, frame.iloc[:1]])), "a.csv")
    with pytest.raises(ValueError, match="XLSX"):
        load_export(b"no", "a.txt")


def test_missing_neutral_unmapped_zero_and_comment_identity():
    frame = pd.read_csv(FIXTURE)
    key, original, comments, audit = load_export(encode(frame), "same.csv")
    assert original.iloc[0]["q5_knowledge"] == 3
    assert original.iloc[29]["q3_knowledge_status"] == "missing"
    assert original.iloc[29]["training_organization_status"] == "unmapped"
    assert audit["invalid_counts"]["training_organization"] == 1
    assert original.iloc[0]["intent"] == 0 and original.iloc[1]["intent"] is None
    assert set(comments.reviewer_status) == {"pending"}
    frame.loc[0, EXPORT_COLUMNS["how_can_we_improve"]] += " changed"
    frame.loc[0, EXPORT_COLUMNS["q4_knowledge"]] = "unknown label"
    new_key, updated, changed, _ = load_export(encode(frame), "same.csv")
    assert new_key != key
    assert updated.iloc[0]["q4_knowledge_status"] == "unmapped"
    before = comments.set_index("private_record_key")
    after = changed.set_index("private_record_key")
    assert before.loc["SYN001:how_can_we_improve", "content_fingerprint"] != after.loc["SYN001:how_can_we_improve", "content_fingerprint"]


def test_equivalent_integer_and_decimal_score_serialization():
    frame = pd.read_csv(FIXTURE, dtype=object)
    key = load_export(encode(frame), "a.csv")[0]
    frame[EXPORT_COLUMNS["intent"]] = frame[EXPORT_COLUMNS["intent"]].map(lambda v: f"{float(v):.1f}" if pd.notna(v) else v)
    assert load_export(encode(frame), "a.csv")[0] == key
