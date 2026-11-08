"""Release approved semantic comment evidence; raw originals remain local."""
import hashlib
import uuid

import pandas as pd

from analysis import validate_responses, audience_mask, publishable
from feedback import FIELDS, summarize_themes


def prepare_review_packet(comments):
    """PRIVATE packet for meaning/privacy review; nothing is auto-approved."""
    packet = []
    for row in pd.DataFrame(comments).to_dict("records"):
        text = row.get("original_text")
        if row.get("source_field") not in FIELDS or not isinstance(text, str) or not text.strip():
            continue
        packet.append(dict(response_id=str(row["response_id"]), source_field=row["source_field"],
            original_text=text, language=row.get("language"),
            content_fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            reviewer_status="pending", privacy_screened=False, approved_paraphrase=None,
            approved_paraphrase_fingerprint=None, theme_ids=[]))
    return packet


def build_comment_evidence(responses, comments, reviews, dataset_key, audience, max_per_field=50):
    """Return AI evidence plus a PRIVATE opaque-ID lineage map.

    Approval requires a current source fingerprint, explicit privacy screening,
    and a fingerprint binding the exact approved paraphrase. Only comments with
    a publishable reviewed theme in this audience/field are eligible.
    """
    if not isinstance(max_per_field, int) or not 1 <= max_per_field <= 200:
        raise ValueError("max_per_field must be between 1 and 200.")
    frame = validate_responses(responses)
    selected = audience_mask(frame, audience)
    if not publishable(pd.Series(True, index=frame.index), selected) or reviews is None:
        return [], {}, []
    # Reuse aggregate checks, including unknown codes, duplicates, complements,
    # and current response roles; never trust audience claims in a review file.
    summary = summarize_themes(frame, comments, reviews, dataset_key, audience)
    allowed = {(t["source_field"], t["theme_id"]) for t in summary["themes"]}
    current = {(str(c["response_id"]), c["source_field"]): c
               for c in pd.DataFrame(comments).to_dict("records")}
    ids = set(frame.loc[selected, "id"])
    evidence, lineage, coverage = [], {}, []
    for field in FIELDS:
        eligible = []
        for r in pd.DataFrame(reviews).to_dict("records"):
            identity = (str(r.get("response_id")), r.get("source_field"))
            original = current.get(identity, {}).get("original_text")
            paraphrase = r.get("approved_paraphrase")
            if (identity[0] not in ids or identity[1] != field or r.get("reviewer_status") != "approved"
                or r.get("privacy_screened") is not True or not isinstance(original, str)
                or not original.strip() or not isinstance(paraphrase, str) or not paraphrase.strip()
                or len(paraphrase) > 1200):
                continue
            if (r.get("content_fingerprint") != hashlib.sha256(original.encode("utf-8")).hexdigest()
                or r.get("approved_paraphrase_fingerprint") != hashlib.sha256(paraphrase.encode("utf-8")).hexdigest()):
                continue
            theme_ids = r.get("theme_ids", [])
            if not isinstance(theme_ids, list) or not all(isinstance(t, str) and (field, t) in allowed for t in theme_ids) or not theme_ids:
                continue
            eligible.append((identity, r))
        for identity, r in eligible[:max_per_field]:
            identifier = "C_" + uuid.uuid4().hex
            evidence.append(dict(comment_evidence_id=identifier, source_field=field,
                approved_paraphrase=r["approved_paraphrase"], theme_ids=sorted(set(r["theme_ids"])),
                review_status="approved_privacy_screened"))
            lineage[identifier] = dict(response_id=identity[0], source_field=field,
                content_fingerprint=r["content_fingerprint"], dataset_key=dataset_key, audience=audience)
        # Do not expose an exact small eligible count in the outbound metadata.
        coverage.append(dict(source_field=field,
            selection="first qualifying approved records in local review-file order",
            sample_limit=max_per_field, truncated=len(eligible) > max_per_field,
            represents="illustrative reviewed sample, not all respondents or theme prevalence"))
    return evidence, lineage, coverage
