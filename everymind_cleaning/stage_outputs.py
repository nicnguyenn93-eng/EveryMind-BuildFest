"""Publish inspectable raw, cleaned, and censored stages together."""

import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile

from . import everymind_clean as ec
from .output_utils import finalize_outputs


def write_stage_outputs(result, root, source_path):
    root, source = Path(root).resolve(), Path(source_path).resolve()
    if result.cleaned_stage.empty or result.censored_stage.empty:
        raise ValueError("Both cleaned and censored stage snapshots are required.")
    if not result.privacy_summary.get("tool_connected"):
        raise ValueError("A connected privacy tool is required to publish the censored stage.")
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    key = result.audit.dataset_key
    if source_sha[:12] != key:
        raise ValueError("The source changed during processing; no results published.")
    raw_root = root / "raw"
    source_is_raw = source.is_relative_to(raw_root.resolve())
    raw_source = source if source_is_raw else raw_root / key / source.name
    paths = {
        "raw_source": raw_source,
        "cleaned": root / "cleaned" / key / f"cleaned_{key}.csv",
        "censored": root / "censoring" / key / f"censored_{key}.csv",
        "audit": root / "reports" / key / f"audit_report_{key}.md",
        "review": root / "reports" / key / f"mapping_review_{key}.csv",
        "private_comments": root / "censoring" / key / "private" / f"comments_private_{key}.csv",
        "distress_review": root / "reports" / key / "private" / f"distress_review_{key}.csv",
        "privacy_review": root / "censoring" / key / "private" / f"presidio_review_{key}.csv",
        "privacy_summary": root / "censoring" / key / f"presidio_summary_{key}.json",
        "manifest": root / "reports" / key / "manifest.json",
        "guide": root / "README.md",
    }
    for name, path in paths.items():
        if not path.resolve().is_relative_to(root):
            raise ValueError("An output path escapes the configured data directory.")
        if name != "raw_source" and path.resolve() == source:
            raise ValueError("An output would overwrite the source.")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Output paths must be regular files.")
    frames = {"cleaned": result.cleaned_stage, "censored": result.censored_stage}
    if list(result.cleaned_stage.columns) != list(result.censored_stage.columns):
        raise ValueError("Cleaned and censored stage columns must align.")
    comment_fields = set(result.privacy_review.field)
    metadata = [c for c in result.cleaned_stage if c not in comment_fields]
    if not result.cleaned_stage[metadata].equals(result.censored_stage[metadata]):
        raise ValueError("Censoring changed non-comment fields.")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stages-", dir=root) as directory:
        temporary = Path(directory)
        legacy = ec.write_outputs(result, temporary / "outputs", temporary / "private")
        staged = {name: legacy[name] for name in (
            "audit", "review", "private_comments", "distress_review", "privacy_review", "privacy_summary"
        )}
        if not source_is_raw:
            staged["raw_source"] = temporary / ("source" + source.suffix)
            staged["raw_source"].write_bytes(source_bytes)
        stages = [{"stage": "raw", "path": str(raw_source.relative_to(root)), "sha256": source_sha,
                   "description": "Unmodified source file; source_row in later stages starts at 2 after its header."}]
        for name, frame in frames.items():
            staged[name] = temporary / paths[name].name
            payload = frame.to_csv(index=False)
            staged[name].write_text(payload, encoding="utf-8", newline="")
            with staged[name].open(encoding="utf-8", newline="") as handle:
                if list(csv.reader(handle, strict=True)) != list(csv.reader(io.StringIO(payload, newline=""), strict=True)):
                    raise ValueError("Stage CSV verification failed.")
            stages.append({"stage": name, "path": str(paths[name].relative_to(root)),
                           "rows": len(frame), "columns": len(frame.columns),
                           "sha256": hashlib.sha256(staged[name].read_bytes()).hexdigest()})
        manifest = {
            "dataset_key": key, "source_sha256": source_sha,
            "stages": stages, "linkage_columns": ["source_row", "original_id", "response_id"],
            "cleaned_comments": "normalized original comments before Presidio",
            "censored_comments": "same columns; only comment values replaced",
            "outputs": {name: str(path.relative_to(root)) for name, path in paths.items()},
            "review_required": True,
        }
        staged["manifest"] = temporary / "manifest.json"
        staged["manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if json.loads(staged["manifest"].read_text()) != manifest:
            raise ValueError("Stage manifest verification failed.")
        staged["guide"] = temporary / "README.md"
        guide = ["# Local survey data stages", "", f"Latest completed dataset: `{key}`.", "",
                 "| Order | Stage | Data |", "| --- | --- | --- |"]
        descriptions = {
            "raw": "Original source file",
            "cleaned": "John's cleaned values with normalized, uncensored comments",
            "censored": "Same columns as cleaned; comment values replaced by Presidio",
        }
        for number, stage in enumerate(stages):
            guide.append(f"| {number} | {descriptions[stage['stage']]} | [{stage['path']}]({stage['path']}) |")
        guide += ["", "Use `source_row`, `original_id`, and `response_id` to trace retained rows between stages.",
                  "Source row numbers start at 2 after the original header; dropped rows are recorded in the audit.",
                  f"[Manifest and file hashes](reports/{key}/manifest.json). Reports contain cleaning audits and mapping reviews.",
                  "The censoring stage includes before/after review files in its private/ subfolder.",
                  "Earlier mixed-layout outputs are preserved in archive/. Standalone Presidio runs use censoring/baseline/.",
                  "These files retain local linkage and source information; censored text still requires review.", ""]
        staged["guide"].write_text("\n".join(guide), encoding="utf-8")
        # Input can already be inside raw/. It is never replaced in that case.
        for name in staged:
            paths[name].parent.mkdir(parents=True, exist_ok=True)
        finalize_outputs([(path, paths[name]) for name, path in staged.items()])
    return paths
