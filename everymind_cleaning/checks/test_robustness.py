"""Generated robustness matrix on synthetic data: `python -m pytest checks -q`.

Invariants:
  1. Safety: no input ever maps to a different label than intended (values or headers).
  2. Harmless formatting (case, spacing, Unicode, punctuation, accents) maps automatically.
  3. Typos and unknown values go to review; they are never applied.
  4. Format drift and conflicting IDs are reported (warn / block), not passed silently.
"""
import io
import os
import random
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import everymind_clean as ec  # noqa: E402
import release as rl  # noqa: E402
from checks.fixtures import header, synthetic_frame  # noqa: E402

warnings.simplefilter("ignore", UserWarning)
CFG = ec.load_config("schema.json", "mapping_registry.json")
VOCABS = ["likert5", "county", "role", "form_language"]
PV = {v: ec._prep_vocab(CFG["vocab"][v]) for v in VOCABS}

FORMATTING = {
    "upper": str.upper, "lower": str.lower, "title": str.title, "padded": lambda s: f"  {s}  ",
    "double space": lambda s: s.replace(" ", "  "), "tab/newline": lambda s: s.replace(" ", "\t") + "\n",
    "nbsp": lambda s: s.replace(" ", " "), "zero-width": lambda s: "​" + s + "‎",
    "curly apostrophe": lambda s: s.replace("'", "’"), "BOM": lambda s: "﻿" + s,
    "fullwidth": lambda s: "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s),
    "trailing period": lambda s: s + ".", "quoted": lambda s: f'"{s}"', "parenthesized": lambda s: f"({s})",
    "hyphens": lambda s: s.replace(" ", "-"), "underscores": lambda s: s.replace(" ", "_"),
    "no apostrophe": lambda s: s.replace("'", ""), "accent": lambda s: s.replace("e", "é", 1),
}


def _typos(s):
    rnd = random.Random(s)
    out = []
    for _ in range(4):
        i = rnd.randrange(1, max(2, len(s) - 1))
        out += [s[:i] + s[i + 1:], s[:i] + s[i] + s[i:], s[:i - 1] + s[i] + s[i - 1] + s[i + 1:]]
    return sorted({t for t in out if t != s})


def _labels(vocab):
    """Every canonical label and alias, with the canonical label it must map to."""
    v = CFG["vocab"][vocab]
    return [(lab, ec.map_value(lab, PV[vocab])[0]) for lab in [*v["canonical"], *v.get("aliases", {})]]


VALUE_CASES = [(v, raw, target) for v in VOCABS for raw, target in _labels(v)]


@pytest.mark.parametrize("vocab,raw,target", VALUE_CASES)
def test_formatting_variants_map_automatically(vocab, raw, target):
    for name, f in FORMATTING.items():
        lab, how, status = ec.map_value(ec.clean_str(f(raw)), PV[vocab])
        assert (lab, status) == (target, ec.VALID), f"{name}: {f(raw)!r} -> {lab!r} ({status})"


@pytest.mark.parametrize("vocab,raw,target", VALUE_CASES)
def test_typos_never_map_to_another_label(vocab, raw, target):
    for t in _typos(raw):
        lab, how, status = ec.map_value(ec.clean_str(t), PV[vocab])
        assert status != ec.VALID or lab == target, f"{t!r} -> {lab!r}"


MUST_REVIEW = {  # plausible inputs whose meaning is not certain: never auto-applied
    "likert5": ["-1", "1.", "(4)", "0", "6", "4.5", "Agree strongly", "Somewhat agree", "Not agree", "Agree/Disagree",
                "Strongly", "Neither", "Unsure", "Don't know", "Strongly agre", "Strongy disagree", "Disagre",
                "Muy de acuerdo", "Algo de acuerdo", "4 - Disagree", "Strongly agree (1)",
                "Very disagree", "Dissatisfied", "None", "-", "null", "nan"],
    "county": ["Montgomery County, PA", "Montgomery, TX", "Prince William", "Prince George", "Arundel", "Anne",
               "Queen Anne", "Baltimore City", "Baltimore County", "Howard", "Washington", "Fairfax City",
               "Harrison", "Montgomery and Prince George's", "AA/PG", "Virtual", "MD", "Maryland", "Other", "Mont."],
    "role": ["Teacher", "Counselor", "Parent of a student", "Student teacher", "Former student", "Students",
             "Grandparent", "Guardian", "Other: neighbor", "Youth", "Student and parent"],
    "form_language": ["en", "es", "EN-US", "Inglés", "Spanish (US)", "English (UK)", "French", "English/Spanish"],
}


@pytest.mark.parametrize("vocab,raw", [(v, r) for v, rs in MUST_REVIEW.items() for r in rs])
def test_uncertain_values_go_to_review(vocab, raw):
    lab, how, status = ec.map_value(ec.clean_str(raw), PV[vocab])
    assert status != ec.VALID, f"{raw!r} auto-mapped to {lab!r} via {how}"


HEADER_EDITS = {
    "upper": str.upper, "trailing ?": lambda s: s + "?", "nbsp": lambda s: s.replace(" ", " "),
    "double space": lambda s: s.replace(" ", "  "), "prefix": lambda s: "Q5. " + s, "html": lambda s: f"<b>{s}</b>",
    "drop first word": lambda s: " ".join(s.split()[1:]), "drop last word": lambda s: " ".join(s.split()[:-1]),
    "truncate": lambda s: s[:40], "typo": lambda s: s[:len(s) // 2] + s[len(s) // 2 + 1:],
    "before->after": lambda s: s.replace("before", "after").replace("Now think back to", "Now think about"),
}


@pytest.mark.parametrize("column", [c for c, s in CFG["columns"].items() if s["type"] != "drop"])
def test_header_drift_never_assigns_wrong_column(column):
    base = synthetic_frame(CFG)
    h = header(CFG, column)
    for name, f in HEADER_EDITS.items():
        new = f(h)
        if not new or new == h:
            continue
        try:
            df = rl.match_input(base.rename(columns={h: new}), CFG, ec.Audit())
        except ec.SchemaError:
            continue  # loud failure is acceptable
        owners = [c for c, (src, _) in df.attrs["column_methods"].items() if src == new]
        assert owners in ([], [column]), f"{name}: {new!r} assigned to {owners}"


@pytest.mark.parametrize("raw,code", [("Totalmente en desacuerdo", 1), ("En desacuerdo", 2),
                                      ("Ni de acuerdo ni en desacuerdo", 3), ("De acuerdo", 4),
                                      ("Totalmente de acuerdo", 5), ("TOTALMENTE DE ACUERDO.", 5)])
def test_spanish_likert_approved(raw, code):
    lab, how, status = ec.map_value(ec.clean_str(raw), PV["likert5"])
    assert (CFG["vocab"]["likert5"]["canonical"][lab], status) == (code, ec.VALID)


def _one(column, value, **edits):
    x = synthetic_frame(CFG).astype(object)
    x.loc[0, header(CFG, column)] = value
    for c, v in edits.items():
        x.loc[0, header(CFG, c)] = v
    return rl.clean_frame(x, CFG)


@pytest.mark.parametrize("raw,value,status", [
    ("0", 0, "valid"), ("10", 10, "valid"), (" 7 ", 7, "valid"), ("7.0", 7, "valid"), (7, 7, "valid"),
    ("７", 7, "valid"), ("10 - Extremely likely", 10, "valid"), ("0 - Not at all likely", 0, "valid"),
    ("-1", None, "invalid"), ("11", None, "invalid"), ("7.5", None, "invalid"), ("1e1", None, "invalid"),
    ("7/10", None, "invalid"), ("8 or 9", None, "invalid"), ("8-9", None, "invalid"), ("seven", None, "invalid"),
    ("Very likely", None, "invalid"), ("N/A", None, "declined"), ("Prefer not to say", None, "declined"),
])
def test_score_parsing(raw, value, status):
    d = _one("recommend", raw).data
    assert d.recommend__status.iloc[0] == status
    assert (pd.isna(d.recommend.iloc[0]) if value is None else d.recommend.iloc[0] == value)


@pytest.mark.parametrize("raw,value", [("4", 4), (4, 4), ("4.0", 4), (4.0, 4), ("4 - Agree", 4), ("Agree (4)", 4),
                                       ("-1", None), ("1.", None), ("(4)", None), ("4 - Disagree", None), (True, None)])
def test_likert_codes(raw, value):
    d = _one("identify_after", raw).data
    assert (pd.isna(d.identify_after.iloc[0]) if value is None else d.identify_after.iloc[0] == value)


@pytest.mark.parametrize("raw,ok", [
    ("2026-10-01", True), ("2026-10-01 00:00:00", True), ("2026-10-01T00:00:00Z", True), ("2026/10/01", True),
    (pd.Timestamp("2026-10-01"), True), ("10/01/2026", False), ("1/10/2026", False), ("Oct 1, 2026", False),
    ("45931", False), ("2026-13-01", False), ("2026-02-30", False), ("26-10-01", False), ("TBD", False),
])
def test_dates_are_iso_only(raw, ok):
    d = _one("training_date", raw).data
    assert (d.training_date__status.iloc[0] == ec.VALID) is ok
    assert (d.training_date.iloc[0] == pd.Timestamp("2026-10-01")) if ok else pd.isna(d.training_date.iloc[0])


def test_mixed_utc_offsets_keep_wall_clock():
    d = _one("completion_time", "2026-10-01T12:01:00-04:00", start_time="2026-10-01 12:00:00Z").data
    assert d.duration_seconds.iloc[0] == 60


@pytest.mark.parametrize("raw,student,caregiver,status", [
    ("Student;Caregiver/parent", True, True, "valid"), ("Student; Caregiver/parent;", True, True, "valid"),
    ("Student,Caregiver/parent", True, True, "valid"), ("Student | Caregiver/parent", True, True, "valid"),
    ("Student;Student", True, False, "valid"), ("Parent/caregiver", False, True, "valid"),
    ("Student/Parent", None, None, "unmapped"), ("Teacher", None, None, "unmapped"),
    ("Teacher;Caregiver/parent", None, True, "partially_mapped"), ("Student, Teacher", None, None, "unmapped"),  # fallback split is all-or-nothing
])
def test_role_multiselect(raw, student, caregiver, status):
    d = _one("role", raw).data
    assert d.role__status.iloc[0] == status
    for col, want in (("role_student", student), ("role_caregiver", caregiver)):
        got = d[col].iloc[0]
        assert pd.isna(got) if want is None else bool(got) is want


@pytest.mark.parametrize("ids,blocked", [
    (["1", "1.0", "3", "4", "5", "6"], True), (["1", "01", "3", "4", "5", "6"], True),
    (["a1", "A1", "3", "4", "5", "6"], True), (["001", "002", "003", "004", "005", "006"], False),
])
def test_conflicting_ids_block(ids, blocked):
    x = synthetic_frame(CFG)
    x[header(CFG, "response_id")] = ids
    checks = rl.clean_frame(x, CFG).checks
    row = checks[checks.check.str.startswith("Response IDs unambiguous")]
    assert bool(row["pass"].iloc[0]) is not blocked


@pytest.mark.parametrize("column,value", [("training_date", "10/01/2026"), ("county", "Baltimore"),
                                          ("form_language", "Inglés"), ("recommend", "Very likely"),
                                          ("presenter_engaged", "Muy bueno"), ("role", "Teacher")])
def test_format_drift_warns(column, value):
    x = synthetic_frame(CFG)
    x[header(CFG, column)] = value
    checks = rl.clean_frame(x, CFG).checks
    failed = checks[~checks["pass"]]
    assert failed.check.str.startswith(f"{column}: unrecognised").any()
    assert failed.severity.eq("warn").all()  # drift warns; it does not block release


def test_renamed_optional_question_warns():
    x = synthetic_frame(CFG).rename(columns={header(CFG, "recommend"): "Would you recommend this?"})
    r = rl.clean_frame(x, CFG)
    failed = r.checks[~r.checks["pass"]]
    assert r.data.recommend__status.eq("not_in_export").all()
    assert failed.check.str.startswith("Optional questions present").any()


@pytest.mark.parametrize("name,data,fn", [
    ("utf-8 BOM", synthetic_frame(CFG).to_csv(index=False).encode("utf-8-sig"), "x.csv"),
    ("cp1252", synthetic_frame(CFG).to_csv(index=False).encode("cp1252"), "x.csv"),
    ("utf-16", synthetic_frame(CFG).to_csv(index=False).encode("utf-16"), "x.csv"),
    ("semicolon", synthetic_frame(CFG).to_csv(index=False, sep=";").encode(), "x.csv"),
    ("tsv", synthetic_frame(CFG).to_csv(index=False, sep="\t").encode(), "x.tsv"),
    ("reordered", synthetic_frame(CFG).iloc[:, ::-1].to_csv(index=False).encode(), "x.csv"),
    ("comment with comma+newline", synthetic_frame(CFG).assign(**{header(CFG, "improve"): 'a,\n"b"'})
     .to_csv(index=False).encode(), "x.csv"),
])
def test_file_variants_read(name, data, fn):
    r = rl.run_pipeline(data, "schema.json", "mapping_registry.json", filename=fn)
    assert len(r.data) == 6 and r.checks.loc[r.checks.severity.eq("block"), "pass"].all()


def test_empty_and_header_only_exports():
    with pytest.raises(ec.SchemaError, match="empty"):
        rl.run_pipeline(b"", "schema.json", "mapping_registry.json", filename="x.csv")
    r = rl.run_pipeline(synthetic_frame(CFG).head(0).to_csv(index=False).encode(), "schema.json",
                        "mapping_registry.json", filename="x.csv")
    with pytest.raises(ValueError, match="At least one response"):
        rl.require_ready(r.checks)
