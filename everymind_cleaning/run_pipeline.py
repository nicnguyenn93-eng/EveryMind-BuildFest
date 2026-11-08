"""Run John's cleaner with the existing local Presidio baseline."""

import argparse
import logging
from pathlib import Path

from . import everymind_clean as ec, privacy_adapter, release
from .presidio_bridge import PresidioBridge
from .language_routing import LanguageDetectionError
from .stage_outputs import write_stage_outputs
from everymind_censoring.redact_pii import RAW_DATA, PRIVATE_DATA, RedactionError


PACKAGE = Path(__file__).resolve().parent
SCHEMA = PACKAGE / "schema.json"
REGISTRY = PACKAGE / "mapping_registry.json"
DEFAULT_INPUT = RAW_DATA / "BuildFest_EveryMind_Survey_Data_FULL.xlsx"
DEFAULT_OUTPUT_DIR = PRIVATE_DATA


def output_directories(dataset_key, output_dir=DEFAULT_OUTPUT_DIR):
    root = Path(output_dir).expanduser().absolute()
    if not root.resolve().is_relative_to(PRIVATE_DATA.resolve()):
        raise RedactionError("Generated survey outputs must stay inside private_data/.")
    outputs = root / "censoring" / dataset_key
    private = outputs / "private"
    for path in (root / "raw", root / "cleaned", root / "reports", outputs, private):
        if not path.resolve().is_relative_to(PRIVATE_DATA.resolve()):
            raise RedactionError("Generated survey outputs must stay inside private_data/.")
    return outputs, private


def run(input_path=DEFAULT_INPUT, output_dir=DEFAULT_OUTPUT_DIR, *, bridge=None):
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise RedactionError(f"Input file not found: {source}")
    # Reject invalid destinations before loading the large models.
    output_directories("preflight", output_dir)
    bridge = bridge if bridge is not None else PresidioBridge()
    with privacy_adapter.using(bridge, "local Presidio baseline (review required)"):
        result = release.run_pipeline(source, SCHEMA, REGISTRY)
        release.require_ready(result.checks)
        output_directories(result.audit.dataset_key, output_dir)
        paths = write_stage_outputs(result, output_dir, source)
    return result, paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    logging.getLogger("presidio-analyzer").disabled = True
    logging.getLogger("presidio-anonymizer").disabled = True
    try:
        result, paths = run(args.input, args.output_dir)
    except (RedactionError, LanguageDetectionError) as error:
        parser.exit(1, f"Pipeline failed: {error}\n")
    except ec.SchemaError as error:
        parser.exit(1, f"Pipeline schema error: {error}\n")
    except Exception:
        # Library errors may include raw responses; keep diagnostics local.
        parser.exit(1, "Pipeline failed during cleaning, validation, or file I/O; no successful output publication. Inspect locally without logging responses.\n")
    summary = result.privacy_summary
    print(f"Data rows: {len(result.cleaned_stage):,}; cleaned columns: {len(result.cleaned_stage.columns)}; censored columns: {len(result.censored_stage.columns)}")
    print(f"Checks passed: {int(result.checks['pass'].sum())}/{len(result.checks)}")
    print(f"Comments: {summary['comments']:,}; changed: {summary['changed']:,}; unchanged: {summary['unchanged']:,}; blank: {summary['blank']:,}")
    print(f"Detections: {sum(summary['detections_by_entity_type'].values()):,}; form-language disagreements: {summary['form_language_disagreements']:,}")
    print(f"Language fallbacks: {summary['language_fallbacks']:,}; language reviews required: {summary['language_review_required']:,}")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
