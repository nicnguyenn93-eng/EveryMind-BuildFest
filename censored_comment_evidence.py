"""User-authorized written responses from the verified censored stage only."""

import hashlib
import json

import pandas as pd

from analysis import audience_mask, publishable, validate_responses
from cleaned_analysis import adapt_cleaned
from everymind_cleaning.censored_data import validate_censored_columns

INPUT_POLICY = "censored_comments_v1"
FIELDS = (("most_valuable", "most_valuable"), ("improve", "how_can_we_improve"))


def build_censored_comment_evidence(export, audience):
    """Include every nonblank selected response, without claiming human review.

    The caller must obtain export through load_censored_export. Original comments,
    IDs, source rows, dates, locations and other individual metadata never leave
    this function. Opaque citation IDs bind the dataset, audience, field and text.
    """
    validate_censored_columns(export.data)
    responses, _ = adapt_cleaned(export.data)
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    if not publishable(pd.Series(True, index=frame.index), selected):
        return []
    evidence = []
    for position, (_, row) in enumerate(export.data.iterrows()):
        if not selected.iloc[position]:
            continue
        for source, field in FIELDS:
            text = row.get(source + "__redacted")
            if not isinstance(text, str) or not text.strip():
                continue
            identity = json.dumps([export.dataset_key, audience, position, field, text], ensure_ascii=False)
            identifier = "CC_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
            evidence.append(dict(dataset_key=export.dataset_key, audience=audience,
                comment_evidence_id=identifier, source_field=field,
                language=row[source + "__lang"], censored_text=text,
                review_status="automatically_censored", sharing_basis="user_authorized"))
    return evidence
