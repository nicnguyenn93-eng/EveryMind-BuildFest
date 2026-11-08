"""
pipeline_checks.py - test runs that prove the pipeline generalizes beyond the one export.

Each check builds a perturbed copy of the real export in memory, runs the full pipeline on it,
and compares against what should happen. Used by the notebook (section 13) and by pytest
(checks/test_cleaning.py) so both report the same results.
"""
from __future__ import annotations

import hashlib
import io
import warnings

import pandas as pd

if __package__:
    from . import everymind_clean as ec, privacy_adapter
else:
    import everymind_clean as ec
    import privacy_adapter

from pathlib import Path

warnings.simplefilter("ignore")

# Independently computed on the original export (team plan, section 8, reproduced in Excel by Role 5)
EXPECTED_ORIGINAL = {
    "n_responses": 1299,
    "identify: agree before": 938, "identify: agree after": 1168,
    "describe_988: agree before": 604, "describe_988: agree after": 1175,
    "when_988: agree before": 723, "when_988: agree after": 1199,
    "n_students": 1080,
    "recommend mean (students)": 7.22, "recommend n (students)": 1051,
    "recommend mean (non-students)": 9.38, "recommend n (non-students)": 215,
    "unsure on either 988 post item": 154, "...of whom students": 135,
    "call intent valid n": 293,
}


def _raw(path) -> pd.DataFrame:
    return pd.read_excel(path, dtype=object, keep_default_na=False, na_values=[""])


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Survey Data", index=False)
    return buf.getvalue()


def _col(df, needle):
    return next(c for c in df.columns if needle.casefold() in c.casefold())


def _run(data: bytes, name: str, schema, registry):
    return ec.run_pipeline(data, schema, registry, filename=name)


def run_all(data_path, schema=None, registry=None) -> pd.DataFrame:
    """Run cleaning checks without consuming or disconnecting a real redactor."""
    root = Path(__file__).resolve().parent
    schema = schema or root / "schema.json"
    registry = registry or root / "mapping_registry.json"
    with privacy_adapter.using():
        return _run_all(data_path, schema, registry)


def _run_all(data_path, schema, registry) -> pd.DataFrame:
    cfg = ec.load_config(schema, registry)
    raw = _raw(data_path)
    base = ec.run_pipeline(data_path, schema, registry)
    base_h = ec.headline_numbers(base.data, cfg)
    results = []

    def record(name, ok, detail=""):
        results.append({"test": name, "pass": bool(ok), "detail": detail})

    # 1. Original export reproduces the independently computed numbers
    exp = ec.check_expected(base_h, EXPECTED_ORIGINAL)
    record("Original export matches independent counts", exp["pass"].all(),
           f"{int(exp['pass'].sum())}/{len(exp)} metrics match")

    # 2. CSV and XLSX of the same data give identical aggregates
    csv = raw.to_csv(index=False).encode("utf-8")
    h = ec.headline_numbers(_run(csv, "export.csv", schema, registry).data, cfg)
    record("CSV and XLSX give identical aggregates", h == base_h)

    # 3. Header drift: shuffled order, different case, extra spaces, reworded item
    drift = raw.sample(frac=1.0, axis=1, random_state=7).copy()
    ren = {
        _col(drift, "I can describe 988"):
            "Please tell us how much you AGREE or DISAGREE with the statements: I can describe 988 and how it works",
        _col(drift, "Which county"): "  Which COUNTY is this training affiliated with ",
        _col(drift, "recommend the Understanding"):
            "How likely are you to recommend the Understanding 988 training to a friend/colleague? (0-10)",
    }
    drift = drift.rename(columns=ren)
    r = _run(_xlsx_bytes(drift), "drift.xlsx", schema, registry)
    methods = r.data.attrs.get("column_methods", {})
    fuzzy_used = {c: m for c, (_, m) in methods.items() if m.startswith("fuzzy")}
    record("Header drift (reorder, case, rewording) still maps every column",
           ec.headline_numbers(r.data, cfg) == base_h, f"fuzzy matches: {fuzzy_used}")

    # 4. Optional column missing -> runs, feature disabled
    no_call = raw.drop(columns=[_col(raw, "call 988")])
    r = _run(_xlsx_bytes(no_call), "no_call.xlsx", schema, registry)
    record("Missing optional column (call intent) is disabled, not fatal",
           "call_intent" not in r.data.columns and any("call_intent" in d for d in r.audit.disabled))

    # 5. Required column missing -> clear error naming it
    no_req = raw.drop(columns=[_col(raw, "I knew when to use 988")])
    try:
        _run(_xlsx_bytes(no_req), "no_req.xlsx", schema, registry)
        record("Missing required column raises a named error", False, "no error raised")
    except ec.SchemaError as e:
        record("Missing required column raises a named error", "when_before" in str(e), str(e)[:160])

    # 6. Updated file: one appended synthetic record (team plan section 8)
    upd = raw.copy()
    new = upd.iloc[[0]].copy()
    new[_col(upd, "Id")] = 999999
    new[_col(upd, "before you took part in the Understanding 988 training.\u00a0\u00a0.I could describe")] = "Disagree"
    new[_col(upd, "statements..I can describe 988")] = "Agree"
    new[_col(upd, "call 988")] = None
    upd = pd.concat([upd, new], ignore_index=True)
    h = ec.headline_numbers(_run(_xlsx_bytes(upd), "updated.xlsx", schema, registry).data, cfg)
    ok = (h["n_responses"], h["describe_988: agree before"], h["describe_988: agree after"],
          h["call intent valid n"]) == (1300, 604, 1176, 293)
    record("Updated file with one new record gives expected counts", ok,
           f"n={h['n_responses']}, describe before={h['describe_988: agree before']}, "
           f"after={h['describe_988: agree after']}, call intent n={h['call intent valid n']}")

    # 7. Messy values: typos, new labels, out-of-range, duplicates
    messy = raw.copy()
    cc, lk, rc, rl, idc = (_col(messy, "Which county"), _col(messy, "engaged the participants"),
                           _col(messy, "recommend the Understanding"), _col(messy, "Are you a"), _col(messy, "Id"))
    messy.loc[0, cc] = "Prince Georges Co."
    messy.loc[1, cc] = "anne arundel county"
    messy.loc[2, cc] = "Mongomery"              # typo -> review queue with a fuzzy suggestion, not applied
    messy.loc[3, cc] = "Baltimore"              # unknown -> review queue
    messy.loc[4, lk] = "STRONGLY AGREE "
    messy.loc[5, lk] = "Agreeeee"               # unknown Likert -> review queue, never fuzzy
    messy.loc[6, rc] = "11"                     # out of range -> invalid
    messy.loc[7, rc] = "10 - Extremely likely"  # leading number parsed
    messy.loc[8, rl] = "Teacher;Caregiver/parent;"
    messy = pd.concat([messy, messy.iloc[[9]]], ignore_index=True)   # exact duplicate row
    dup = messy.iloc[[10]].copy(); dup[lk] = "Disagree"
    messy = pd.concat([messy, dup], ignore_index=True)               # same ID, different content
    r = _run(_xlsx_bytes(messy), "messy.xlsx", schema, registry)
    d, rq = r.data, r.audit.review_table()
    queued = set(rq["raw_value"])
    checks = {
        "county variants mapped": list(d.loc[:1, "county"]) == ["Prince George's", "Anne Arundel"],
        "county typo queued with suggestion, not applied":
            pd.isna(d.loc[2, "county"]) and rq.set_index("raw_value").loc["Mongomery", "suggestion"] == "Montgomery",
        "unknown county queued": "Baltimore" in queued and d.loc[3, "county__status"] == ec.UNMAPPED,
        "case-variant Likert mapped": d.loc[4, "presenter_engaged"] == 5,
        "unknown Likert queued, not guessed": "Agreeeee" in queued and pd.isna(d.loc[5, "presenter_engaged"]),
        "out-of-range scale invalid": d.loc[6, "recommend__status"] == ec.INVALID,
        "leading number parsed": d.loc[7, "recommend"] == 10,
        "unknown role queued, known role kept": "Teacher" in queued and bool(d.loc[8, "role_caregiver"]),
        "exact duplicate dropped": len(d) == len(raw) + 1,
        "duplicate ID flagged": int(d["flag_duplicate_id"].sum()) == 2,
    }
    record("Messy values handled (typos, unknowns, ranges, duplicates)", all(checks.values()),
           ", ".join(k for k, v in checks.items() if not v) or "all sub-checks passed")

    # 8. Re-running gives byte-identical output
    a = ec.run_pipeline(data_path, schema, registry).data.to_csv(index=False).encode()
    b = ec.run_pipeline(data_path, schema, registry).data.to_csv(index=False).encode()
    record("Deterministic: two runs give identical output",
           hashlib.sha256(a).digest() == hashlib.sha256(b).digest())

    # 9. Privacy tool contract (with a fake tool standing in for the teammate's)
    canary = "Zyxwvut Qrstuvw"
    canary_df = raw.copy()
    canary_df.loc[0, _col(canary_df, "most valuable")] = f"My teacher {canary} explained it well"
    fake = lambda texts, langs: [t.replace(canary, "<PERSON>") for t in texts]
    privacy_adapter.connect(fake, "fake test redactor")
    try:
        r = _run(_xlsx_bytes(canary_df), "canary.xlsx", schema, registry)
        red = r.data["most_valuable__redacted"].fillna("")
        ok = (r.data["most_valuable__privacy"].eq("redacted").any()
              and not red.str.contains(canary).any() and red.str.contains("<PERSON>").any()
              and canary in " ".join(r.private["most_valuable"].dropna()))
        record("Privacy adapter: redacted text public, raw text private only", ok)
        privacy_adapter.connect(lambda texts, langs: texts[:-1], "broken test redactor")
        try:
            _run(_xlsx_bytes(raw), "broken.xlsx", schema, registry)
            record("Privacy adapter rejects a tool that misaligns rows", False)
        except ValueError:
            record("Privacy adapter rejects a tool that misaligns rows", True)
    finally:
        privacy_adapter.disconnect()

    return pd.DataFrame(results)
