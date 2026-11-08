"""Create local review copies of survey comments with baseline Presidio redaction."""

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from importlib import metadata
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DATA = ROOT / "private_data"
RAW_DATA = PRIVATE_DATA / "raw"
CENSORING_DATA = PRIVATE_DATA / "censoring"
REPORTS_DATA = PRIVATE_DATA / "reports"
DEFAULT_INPUT = RAW_DATA / "survey.csv"
DEFAULT_OUTPUT = CENSORING_DATA / "baseline" / "survey_presidio.csv"
COMMENT_FIELDS = (
    "What was the most valuable thing you learned during the training?\u00a0",
    "How can we improve this training in the future?",
)
MODELS = {"en": "en_core_web_lg", "es": "es_core_news_lg"}
MODEL_VERSION = "3.8.0"
LANGUAGES = {
    "en": "en", "english": "en", "english (united states)": "en",
    "es": "es", "español": "es", "español (méxico)": "es",
}
REVIEW_FIELDS = (
    "source_row", "original_id", "field", "language", "original_text",
    "redacted_text", "status", "detections",
)


class RedactionError(ValueError):
    """A safe-to-display error that contains no survey response text."""


@dataclass(frozen=True)
class Detection:
    entity_type: str
    start: int
    end: int
    score: float


@dataclass(frozen=True)
class Redaction:
    text: str
    detections: list[Detection]


def language_code(value, source_row):
    # The exported language label includes a left-to-right mark. Only the routing
    # key is normalized; the original CSV cell is never changed.
    key = value.replace("\u200e", "").replace("\u200f", "").strip().casefold()
    if not key:
        raise RedactionError(f"Missing Language at source row {source_row}.")
    if key not in LANGUAGES:
        raise RedactionError(f"Unsupported Language at source row {source_row}; expected English or Spanish.")
    return LANGUAGES[key]


def read_source(source):
    if not source.is_file():
        raise RedactionError(f"Input CSV not found: {source}")
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        header = next(reader, [])
        if not header or len(header) != len(set(header)):
            raise RedactionError("Input must have a nonempty header with unique column names.")
        required = ("Id", "Language", *COMMENT_FIELDS)
        missing = [name for name in required if name not in header]
        if missing:
            raise RedactionError("Missing required headers: " + ", ".join(missing))
        rows, languages = [], []
        for number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise RedactionError(f"Incorrect column count at source row {number}.")
            languages.append(language_code(row[header.index("Language")], number))
            rows.append(row)
    return header, rows, languages


def check_models():
    problems = []
    for model in MODELS.values():
        try:
            version = metadata.version(model)
        except metadata.PackageNotFoundError:
            problems.append(f"{model} is missing")
        else:
            if version != MODEL_VERSION:
                problems.append(f"{model} must be version {MODEL_VERSION}")
    if problems:
        raise RedactionError("; ".join(problems) + ". Run python -m pip install -r requirements-models.txt during setup.")


class PresidioRedactor:
    def __init__(self, analyzer, anonymizer):
        self.analyzer = analyzer
        self.anonymizer = anonymizer
        self.versions = {
            "python": sys.version.split()[0],
            "packages": {
                name: metadata.version(name) for name in (
                    "presidio-analyzer", "presidio-anonymizer", "spacy", "tldextract",
                )
            },
            "models": {name: metadata.version(name) for name in MODELS.values()},
        }

    def redact(self, text, language):
        results = self.analyzer.analyze(text=text, language=language)
        # Offsets refer to the ORIGINAL text, before the anonymizer resolves
        # overlapping detections. No matched strings enter the JSON summary.
        detections = sorted(
            [Detection(r.entity_type, r.start, r.end, r.score) for r in results],
            key=lambda d: (d.start, d.end, d.entity_type),
        )
        redacted = self.anonymizer.anonymize(text=text, analyzer_results=results)
        return Redaction(redacted.text, detections)


def build_redactor():
    check_models()
    try:
        import spacy
        import tldextract
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider, SpacyNlpEngine
        from presidio_analyzer.predefined_recognizers.generic import email_recognizer
        from presidio_anonymizer import AnonymizerEngine

        class LocalCpuSpacyEngine(SpacyNlpEngine):
            def load(self):
                # Stock load() can download missing models and enable a GPU.
                # Use the same pipelines, with neither behavior permitted.
                check_models()
                spacy.require_cpu()
                self.nlp = {
                    model["lang_code"]: spacy.load(model["model_name"])
                    for model in self.models
                }

        # Keep the built-in email rule and validation, using tldextract's bundled
        # suffix snapshot instead of its default online suffix-list update.
        email_recognizer.tldextract = SimpleNamespace(
            extract=tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
        )
        # Preserve the installed Presidio default NER mappings and ignore list.
        provider = NlpEngineProvider(nlp_engines=(LocalCpuSpacyEngine,))
        provider.nlp_configuration["models"] = [
            {"lang_code": language, "model_name": model}
            for language, model in MODELS.items()
        ]
        analyzer = AnalyzerEngine(
            nlp_engine=provider.create_engine(), supported_languages=list(MODELS),
            log_decision_process=False,
        )
        return PresidioRedactor(analyzer, AnonymizerEngine())
    except RedactionError:
        raise
    except Exception:
        raise RedactionError("Could not load the local Presidio engines. Check the pinned packages and models in the README.") from None


def output_paths(output_path, source):
    destination = Path(output_path).expanduser().absolute()
    if destination.suffix.lower() != ".csv":
        raise RedactionError("Output must have a .csv extension.")
    paths = (destination, destination.with_suffix(".review.csv"), destination.with_suffix(".summary.json"))
    for path in paths:
        if not path.resolve().is_relative_to(PRIVATE_DATA.resolve()):
            raise RedactionError("All outputs must stay inside the Git-ignored private_data/ folder.")
        if path.resolve() == source:
            raise RedactionError("An output would overwrite the source CSV; choose another output name.")
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RedactionError("Output paths must be regular files, not symlinks or directories.")
    return paths


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if list(csv.reader(handle, strict=True)) != rows:
            raise RedactionError("Temporary CSV verification failed.")


def finalize_outputs(staged):
    """Replace the three results only after processing and verification succeed.

    Roll back ordinary replacement errors. Multi-file publication is not a single
    atomic filesystem operation; abrupt process/OS failure can still interrupt it.
    """
    backups = {}
    completed = []
    try:
        for temporary, destination in staged:
            if destination.exists():
                backup = temporary.with_suffix(".backup")
                backup.write_bytes(destination.read_bytes())
                backups[destination] = backup
        for temporary, destination in staged:
            temporary.replace(destination)
            completed.append(destination)
    except OSError:
        for destination in reversed(completed):
            if destination in backups:
                backups[destination].replace(destination)
            else:
                destination.unlink(missing_ok=True)
        raise


def redact_csv(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT, *, redactor_factory=build_redactor):
    source = Path(input_path).expanduser().resolve()
    paths = output_paths(output_path, source)
    header, rows, languages = read_source(source)
    # All headers, row widths, and languages are validated before any detection.
    redactor = redactor_factory()
    comment_indices = [header.index(field) for field in COMMENT_FIELDS]
    id_index = header.index("Id")
    output_rows, review_rows = [header], [list(REVIEW_FIELDS)]
    statuses, by_type = Counter(), Counter()
    by_language = {language: {"records": 0, "comments": 0, "changed": 0, "unchanged": 0, "blank": 0, "detections": Counter()} for language in MODELS}
    for source_row, (row, language) in enumerate(zip(rows, languages), start=2):
        new_row = row.copy()
        counts = by_language[language]
        counts["records"] += 1
        for field, index in zip(COMMENT_FIELDS, comment_indices):
            original = row[index]
            if not original.strip():
                result = Redaction(original, [])
                status = "blank"
            else:
                try:
                    result = redactor.redact(original, language)
                except Exception:
                    # Engine exceptions can contain the input. Never echo them.
                    raise RedactionError(f"Processing failed at source row {source_row}, comment field {comment_indices.index(index) + 1}; existing outputs were not replaced.") from None
                status = "changed" if result.text != original else "unchanged"
            new_row[index] = result.text
            statuses[status] += 1
            counts["comments"] += 1
            counts[status] += 1
            detections = [asdict(d) for d in result.detections]
            for detection in result.detections:
                by_type[detection.entity_type] += 1
                counts["detections"][detection.entity_type] += 1
            review_rows.append([
                str(source_row), row[id_index], field, language, original,
                result.text, status, json.dumps(detections, ensure_ascii=False),
            ])
        output_rows.append(new_row)
    summary = {
        "data_rows": len(rows), "columns": len(header),
        "comment_fields": len(COMMENT_FIELDS), "comments": len(review_rows) - 1,
        "scanned": statuses["changed"] + statuses["unchanged"],
        "changed": statuses["changed"], "unchanged": statuses["unchanged"], "blank": statuses["blank"],
        "detections_by_entity_type": dict(sorted(by_type.items())),
        "by_language": by_language,
        "versions": redactor.versions,
        "configuration": {"device": "cpu", "recognizers": "built-in defaults", "score_threshold": "Presidio default", "replacement": "default entity placeholders", "suffix_list": "bundled offline snapshot"},
    }
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".presidio-", dir=paths[0].parent) as directory:
        staged_paths = [Path(directory) / path.name for path in paths]
        write_csv(staged_paths[0], output_rows)
        write_csv(staged_paths[1], review_rows)
        staged_paths[2].write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if json.loads(staged_paths[2].read_text(encoding="utf-8")) != summary:
            raise RedactionError("Temporary summary verification failed.")
        finalize_outputs(list(zip(staged_paths, paths)))
    return summary, paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                        help="Destination CSV inside private_data/ (default: private_data/censoring/baseline/survey_presidio.csv).")
    args = parser.parse_args(argv)
    # Suppress library diagnostics; decision/error logging can contain input text.
    logging.getLogger("presidio-analyzer").disabled = True
    logging.getLogger("presidio-anonymizer").disabled = True
    try:
        summary, paths = redact_csv(args.input, args.output)
    except (RedactionError, OSError, csv.Error, UnicodeError) as error:
        message = str(error) if isinstance(error, RedactionError) else "File read/write failed; check paths, permissions, and UTF-8 CSV format."
        parser.exit(1, f"Redaction failed: {message}\n")
    print(f"Data rows: {summary['data_rows']:,}; columns: {summary['columns']}")
    print(f"Comments: {summary['comments']:,}; scanned: {summary['scanned']:,}; changed: {summary['changed']:,}; unchanged: {summary['unchanged']:,}; blank: {summary['blank']:,}")
    print(f"Detections: {sum(summary['detections_by_entity_type'].values()):,}")
    for label, path in zip(("CSV", "Review CSV", "Summary JSON"), paths):
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
