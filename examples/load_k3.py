"""Load K3 handoff examples without invoking unfinished app modules."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAMES = ("normalized_responses", "reviewed_comments", "audit", "evidence",
         "theme_summary", "report", "privacy_expectations")


def load_examples():
    return {name: json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))
            for name in NAMES}


if __name__ == "__main__":
    records = load_examples()
    print(f"K3 loaded: {len(records['normalized_responses'])} responses, "
          f"{len(records['reviewed_comments'])} review records, "
          f"{len(records['evidence'])} evidence examples, template report.")
    print("Synthetic handoff only; receiving-team signoff remains pending.")
