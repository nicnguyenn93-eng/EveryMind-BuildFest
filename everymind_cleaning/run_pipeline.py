"""Run John's cleaner with the existing local Presidio baseline."""

import argparse
import logging
from pathlib import Path

from . import everymind_clean as ec, privacy_adapter
from .presidio_bridge import PresidioBridge
from scripts.redact_pii import PRIVATE_DATA, RedactionError


PACKAGE = Path(__file__).resolve().parent
SCHEMA = PACKAGE / "schema.json"
REGISTRY = PACKAGE / "mapping_registry.json"
DEFAULT_INPUT = PRIVATE_DATA / "BuildFest_EveryMind_Survey_Data_FULL.xlsx"
DEFAULT_OUTPUT_DIR = PRIVATE_DATA / "cleaning"


def output_directories(dataset_key, output_dir=DEFAULT_OUTPUT_DIR):
    root = Path(output_dir).expanduser().absolute()
    if not root.resolve().is_relative_to(PRIVATE_DATA.resolve()):
        raise RedactionError("Generated survey outputs must stay inside private_data/.")
    run = root / dataset_key
    outputs, private = run / "outputs", run / "private"
    for path in (outputs, private):
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
        result = ec.run_pipeline(source, SCHEMA, REGISTRY)
        outputs, private = output_directories(result.audit.dataset_key, output_dir)
        expected_paths = [
            outputs / f"cleaned_{result.audit.dataset_key}.csv",
            outputs / f"mapping_review_{result.audit.dataset_key}.csv",
            private / f"comments_private_{result.audit.dataset_key}.csv",
            private / f"distress_review_{result.audit.dataset_key}.csv",
            private / f"presidio_review_{result.audit.dataset_key}.csv",
        ]
        if any(path.resolve() == source for path in expected_paths):
            raise RedactionError("An output would overwrite the input; choose another output directory.")
        paths = ec.write_outputs(result, outputs, private)
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
    except RedactionError as error:
        parser.exit(1, f"Pipeline failed: {error}\n")
    except ec.SchemaError as error:
        parser.exit(1, f"Pipeline schema error: {error}\n")
    except Exception:
        # Library errors may include raw responses; keep diagnostics local.
        parser.exit(1, "Pipeline failed during cleaning, validation, or file I/O; no successful output publication. Inspect locally without logging responses.\n")
    summary = result.privacy_summary
    print(f"Data rows: {len(result.data):,}; columns: {len(result.data.columns)}")
    print(f"Checks passed: {int(result.checks['pass'].sum())}/{len(result.checks)}")
    print(f"Comments: {summary['comments']:,}; changed: {summary['changed']:,}; unchanged: {summary['unchanged']:,}; blank: {summary['blank']:,}")
    print(f"Detections: {sum(summary['detections_by_entity_type'].values()):,}; form-language disagreements: {summary['form_language_disagreements']:,}")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
