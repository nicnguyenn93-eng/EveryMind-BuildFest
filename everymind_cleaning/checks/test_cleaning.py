"""pytest entry point: `python -m pytest checks -q` (set EVERYMIND_DATA to the export path)."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
from everymind_cleaning import pipeline_checks

DATA = os.environ.get("EVERYMIND_DATA", str(ROOT.parent / "private_data" / "BuildFest_EveryMind_Survey_Data_FULL.xlsx"))
RESULTS = pipeline_checks.run_all(DATA) if Path(DATA).exists() else None


@pytest.mark.skipif(RESULTS is None, reason=f"export not found at {DATA}")
@pytest.mark.parametrize("i", range(10))
def test_check(i):
    row = RESULTS.iloc[i]
    assert row["pass"], f"{row['test']}: {row['detail']}"
