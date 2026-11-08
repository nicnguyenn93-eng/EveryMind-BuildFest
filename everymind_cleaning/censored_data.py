"""Read the completed censored stage without reopening any source data."""

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re

import pandas as pd


REGENERATE = "Run python -m everymind_cleaning.run_pipeline to generate a full censored CSV and its manifest."
COMMENT_FIELDS = ("most_valuable", "improve")
ROLE_FLAGS = ("role_student", "role_staff", "role_caregiver", "role_other")
REQUIRED = {"source_row", "original_id", "response_id", "role__status", *ROLE_FLAGS,
            "identify_before", "identify_after", "describe_before", "describe_after", "when_before", "when_after"}


class CensoredExportError(ValueError):
    """Safe-to-display validation error without response contents."""


@dataclass
class CensoredExport:
    path: Path
    root: Path
    source_key: str
    sha256: str
    data: pd.DataFrame
    manifest: dict

    @property
    def dataset_key(self):
        return "censored-sha256:" + self.sha256

    @property
    def manifest_path(self):
        return self.root / "reports" / self.source_key / "manifest.json"


def parse_columns(data, types):
    """Restore CSV scalars explicitly; never interpret the string 'False' by truthiness."""
    identifiers = {"response_id", "original_id"}
    for column, dtype in types.items():
        if column in identifiers:
            continue
        values = data[column]
        try:
            if dtype in ("bool", "boolean") or column in ROLE_FLAGS:
                allowed = {"True", "False"} | ({""} if dtype == "boolean" else set())
                if not values.isin(allowed).all():
                    raise ValueError()
                data[column] = values.map({"True": True, "False": False, "": pd.NA}).astype(dtype if dtype == "boolean" else bool)
            elif re.fullmatch(r"(?:u?int|float|UInt|Int|Float)\d+", dtype):
                data[column] = pd.to_numeric(values.replace("", None), errors="raise").astype(dtype)
            elif dtype.startswith("datetime64"):
                data[column] = pd.to_datetime(values.replace("", None), errors="raise", format="mixed").astype(dtype)
            elif dtype not in ("object", "string", "str"):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise CensoredExportError("Censored CSV scalar types are invalid; " + REGENERATE) from None
    return data


def validate_censored_columns(data):
    if not REQUIRED.issubset(data) or set(COMMENT_FIELDS) & set(data):
        raise CensoredExportError("Expected John's full censored result, not raw or checkpoint data. " + REGENERATE)
    for field in COMMENT_FIELDS:
        if not any(column.startswith(field + "__") for column in data):
            continue  # John's optional comment columns can be absent.
        names = [field + suffix for suffix in ("__redacted", "__privacy", "__lang", "__category")]
        if not set(names).issubset(data):
            raise CensoredExportError("Comment metadata is incomplete. " + REGENERATE)
        text, privacy, language = (data[name] for name in names[:3])
        if (not privacy.isin(["redacted", "blank"]).all()
                or (privacy.eq("blank") & text.str.strip().ne("")).any()
                or (privacy.eq("redacted") & ~language.isin(["en", "es"])).any()):
            raise CensoredExportError("Comment processing is pending or inconsistent. " + REGENERATE)


def load_censored_export(input_path):
    path = Path(input_path).expanduser().resolve()
    if path.suffix.lower() != ".csv" or not path.is_file():
        raise CensoredExportError("Analysis requires an existing censored CSV. " + REGENERATE)
    if path.parent.parent.name != "censoring":
        raise CensoredExportError("Select the completed CSV under censoring/<key>/. " + REGENERATE)
    root, key = path.parents[2], path.parent.name
    if not re.fullmatch(r"[0-9a-f]{12}", key):
        raise CensoredExportError("The censored dataset folder is invalid. " + REGENERATE)
    try:
        manifest = json.loads((root / "reports" / key / "manifest.json").read_text(encoding="utf-8"))
        stages = [stage for stage in manifest["stages"] if stage["stage"] == "censored"]
        if manifest.get("schema_version") != "everymind.stages.v2" or manifest["dataset_key"] != key or len(stages) != 1:
            raise ValueError()
        if not isinstance(manifest.get("outputs"), dict) or not all(isinstance(value, str) for value in manifest["outputs"].values()):
            raise ValueError()
        stage = stages[0]
        if (root / stage["path"]).resolve() != path:
            raise ValueError()
        payload = path.read_bytes()
        fingerprint = hashlib.sha256(payload).hexdigest()
        if fingerprint != stage["sha256"]:
            raise ValueError()
        records = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True))
        header = records[0]
        if (not header or len(set(header)) != len(header) or header != stage["column_names"]
                or len(header) != stage["columns"] or len(records) - 1 != stage["rows"]
                or any(len(row) != len(header) for row in records[1:]) or set(stage["column_types"]) != set(header)
                or not all(isinstance(dtype, str) for dtype in stage["column_types"].values())):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, IndexError, csv.Error):
        raise CensoredExportError("The full censored export or its manifest is missing, outdated, or inconsistent. " + REGENERATE) from None
    data = pd.DataFrame(records[1:], columns=header)
    validate_censored_columns(data)
    data = parse_columns(data, stage["column_types"])
    if (not pd.api.types.is_integer_dtype(data.source_row) or data.source_row.duplicated().any()
            or data.source_row.isna().any() or data.source_row.lt(2).any()):
        raise CensoredExportError("Source-row linkage is invalid. " + REGENERATE)
    return CensoredExport(path, root, key, fingerprint, data, manifest)
