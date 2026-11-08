"""Synthetic survey exports (no real responses or comments) shared by pytest and the notebook."""
import pandas as pd

VALUES = {"response_id": "1", "role": "Student", "training_date": "2026-10-01", "county": "Montgomery",
          "start_time": "2026-10-01 12:00:00", "completion_time": "2026-10-01 12:01:00",
          "form_language": "English", "recommend": "8", "call_intent": "7",
          "most_valuable": "Synthetic learning feedback", "improve": "Synthetic suggestion"}


def header(cfg: dict, column: str) -> str:
    return cfg["columns"][column]["synonyms"][0]


def synthetic_frame(cfg: dict, n: int = 6) -> pd.DataFrame:
    """n raw rows using each column's first schema synonym; first half Student, rest Caregiver/parent."""
    rows = []
    for i in range(n):
        row = {header(cfg, c): VALUES.get(c, "Agree") for c, spec in cfg["columns"].items() if spec["type"] != "drop"}
        row[header(cfg, "response_id")] = str(i + 1)
        row[header(cfg, "role")] = "Student" if i < n // 2 else "Caregiver/parent"
        rows.append(row)
    return pd.DataFrame(rows)
