"""pytest entry point: `python -m pytest checks -q` (set EVERYMIND_DATA to the export path)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pipeline_checks  # noqa: E402

DATA = os.environ.get("EVERYMIND_DATA", str(ROOT / "data" / "BuildFest_EveryMind_Survey_Data_FULL.xlsx"))
RESULTS = pipeline_checks.run_all(DATA) if Path(DATA).exists() else None


@pytest.mark.skipif(RESULTS is None, reason=f"export not found at {DATA}")
@pytest.mark.parametrize("i", range(10))
def test_check(i):
    row = RESULTS.iloc[i]
    assert row["pass"], f"{row['test']}: {row['detail']}"
