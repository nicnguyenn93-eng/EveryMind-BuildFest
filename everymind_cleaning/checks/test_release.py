"""Release contract tests on synthetic data: `python -m pytest checks -q`."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import everymind_clean as ec  # noqa: E402
import release as rl  # noqa: E402
from checks.fixtures import header, synthetic_frame  # noqa: E402

CFG = ec.load_config("schema.json", "mapping_registry.json")
TEXT_COLS = [c for c, s in CFG["columns"].items() if s["type"] == "text"]


def _write_and_reload(result, tmp_path):
    paths = rl.write_release(result, tmp_path / "public", tmp_path / "private", {"run_key": "test"}, CFG)
    return paths, rl.load_clean(paths["cleaned"])


def test_round_trip_preserves_contract(tmp_path):
    # Arrange: a zero score, a missing rating, and a row whose timing cannot be assessed
    raw = synthetic_frame(CFG)
    raw.loc[0, header(CFG, "recommend")] = "0"
    raw.loc[1, header(CFG, "identify_before")] = None
    raw.loc[2, header(CFG, "completion_time")] = None
    result = rl.clean_frame(raw, CFG)

    # Act
    paths, back = _write_and_reload(result, tmp_path)

    # Assert
    assert back.response_id.dtype == "string" and back.response_id.tolist() == [str(i) for i in range(1, 7)]
    assert back.recommend.iloc[0] == 0 and back.recommend__status.iloc[0] == ec.VALID
    assert pd.isna(back.identify_before.iloc[1]) and back.identify_before__status.iloc[1] == ec.SKIPPED
    assert pd.isna(back.identify__change.iloc[1]) and not back.identify__paired_valid.iloc[1]
    assert pd.isna(back.flag_fast.iloc[2]) and back.flag_fast.iloc[0] == False  # noqa: E712 (NA-aware)
    assert back.comparison_group.tolist() == ["Student"] * 3 + ["Nonstudent"] * 3
    for pair in CFG["pairs"]:
        assert back[f"{pair}__paired_valid"].sum() == result.data[f"{pair}__paired_valid"].sum()
    pd.testing.assert_frame_equal(rl.public_data(result.data).reset_index(drop=True), back, check_dtype=False)
    required = ["response_id", "comparison_group", "session_key", *(f"{p}__paired_valid" for p in CFG["pairs"])]
    assert set(required) <= set(back.columns)
    assert not set(TEXT_COLS) & set(back.columns)
    assert "Synthetic" not in paths["cleaned"].read_text()


def test_missing_id_blocks_release(tmp_path):
    raw = synthetic_frame(CFG)
    raw.loc[0, header(CFG, "response_id")] = None
    with pytest.raises(ValueError, match="Release blocked"):
        _write_and_reload(rl.clean_frame(raw, CFG), tmp_path)
    assert not (tmp_path / "public").exists()


def test_high_missingness_warns_but_releases(tmp_path):
    raw = synthetic_frame(CFG)
    raw.loc[1:, header(CFG, "identify_after")] = None
    result = rl.clean_frame(raw, CFG)
    with pytest.warns(UserWarning, match="identify_after valid rate"):
        assert rl.require_ready(result.checks) == ["identify_after valid rate ≥ 90%"]
    _, back = _write_and_reload(result, tmp_path)
    assert back.identify_after.notna().sum() == 1


def test_duplicate_raw_header_rejected():
    raw = synthetic_frame(CFG)
    h = header(CFG, "recommend")
    dup = pd.concat([raw, raw[[h]]], axis=1)  # pandas will read this back as "<h>" and "<h>.1"
    with pytest.raises(ec.SchemaError, match="duplicate column header"):
        rl.run_pipeline(dup.to_csv(index=False).encode(), "schema.json", "mapping_registry.json", filename="x.csv")


def test_non_iso_date_is_invalid_not_guessed():
    raw = synthetic_frame(CFG)
    raw.loc[0, header(CFG, "training_date")] = "03/04/2026"
    out = rl.clean_frame(raw, CFG).data
    assert pd.isna(out.training_date.iloc[0]) and out.training_date__status.iloc[0] == ec.INVALID


def test_contains_and_fuzzy_values_go_to_review():
    raw = synthetic_frame(CFG)
    raw.loc[0, header(CFG, "county")] = "Montgomery Synthetic Office"
    raw.loc[1, header(CFG, "county")] = "Montgomeryy"
    result = rl.clean_frame(raw, CFG)
    assert result.data.county__status.iloc[:2].eq(ec.UNMAPPED).all() and result.data.county.iloc[:2].isna().all()
    review = result.audit.review_table().set_index("raw_value")
    assert review.loc["Montgomery Synthetic Office", "suggested_by"] == "contains (needs review)"
    assert review.loc["Montgomeryy", "suggested_by"].startswith("fuzzy")
