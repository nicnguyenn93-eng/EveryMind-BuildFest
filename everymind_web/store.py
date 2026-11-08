"""Local dataset handles and serialized cleaning jobs. Paths stay on the server."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
import uuid

from everymind_cleaning.censored_data import load_censored_export
from everymind_cleaning.run_pipeline import run as run_pipeline
from .aggregates import Dashboard


class DatasetError(ValueError):
    pass


class StaleDatasetError(DatasetError):
    pass


class DatasetStore:
    def __init__(self, root, pipeline=run_pipeline):
        self.root = Path(root).resolve()
        self.pipeline = pipeline
        self.paths, self.dashboards, self.jobs = {}, {}, {}
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="survey-cleaning")

    def close(self):
        self.executor.shutdown(wait=True)

    def register(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise DatasetError("Dataset must stay in the local private data folder.")
        export = load_censored_export(path)
        with self.lock:
            if export.sha256 not in self.dashboards:
                self.dashboards[export.sha256] = Dashboard(export)
            self.paths[export.sha256] = path
        return self.describe(export)

    @staticmethod
    def describe(export):
        n = len(export.data)
        return dict(dataset_id=export.sha256, dataset_key=export.dataset_key,
                    label=f"Processed survey {export.source_key}",
                    rows=n if n == 0 or n >= 10 else None, columns=len(export.data.columns))

    def discover(self):
        found = []
        candidates = []
        for path in (self.root / "censoring").glob("*/censored_*.csv"):
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for _, path in sorted(candidates, reverse=True):
            try:
                found.append(self.register(path))
            except (ValueError, OSError):
                continue  # Incomplete/old exports are never offered as usable data.
        return found

    def resolve(self, identifier):
        if not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise DatasetError("Unknown processed dataset. Reload the dataset list.")
        with self.lock:
            path = self.paths.get(identifier)
        if path is None:
            self.discover()
            path = self.paths.get(identifier)
        if path is None:
            raise DatasetError("Unknown processed dataset. Reload the dataset list.")
        try:
            export = load_censored_export(path)
        except (ValueError, OSError):
            raise StaleDatasetError("This processed dataset changed or became unavailable. Reload it.") from None
        if export.sha256 != identifier:
            raise StaleDatasetError("This processed dataset changed. Reload it before continuing.")
        return export

    def dashboard(self, identifier, audience):
        self.resolve(identifier)  # Recheck file/manifest even when aggregates are cached.
        return self.dashboards[identifier].for_audience(audience)

    def submit(self, payload, suffix):
        digest = hashlib.sha256(payload).hexdigest()
        source = self.root / "raw" / "uploads" / digest / ("upload" + suffix)
        if not source.resolve().is_relative_to(self.root) or source.is_symlink():
            raise DatasetError("Invalid local upload destination.")
        token = uuid.uuid4().hex
        with self.lock:
            source.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                if source.read_bytes() != payload:
                    raise DatasetError("An existing source differs; it has been preserved.")
            else:
                fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=source.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(payload)
                    os.replace(temporary, source)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            self.jobs[token] = dict(job_id=token, status="processing", message="Cleaning and censoring locally.")
            self.executor.submit(self._process, token, source, digest)
        return token

    def _process(self, token, source, digest):
        try:
            candidate = self.root / "censoring" / digest[:12] / f"censored_{digest[:12]}.csv"
            if candidate.exists():
                export = load_censored_export(candidate)
                if export.manifest["source_sha256"] != digest:
                    raise DatasetError("Source fingerprint mismatch.")
            else:
                _, paths = self.pipeline(source, self.root)
                candidate = paths["censored"]
            dataset = self.register(candidate)
            with self.lock:
                self.jobs[token] = dict(job_id=token, status="ready", dataset=dataset, message="Processed dataset is ready.")
        except Exception:
            with self.lock:
                self.jobs[token] = dict(job_id=token, status="failed",
                    message="Local processing failed. Check the workbook layout, languages, and installed models. Existing outputs were preserved.")

    def job(self, token):
        with self.lock:
            value = self.jobs.get(token)
            if value is None:
                raise DatasetError("Unknown processing job. Reload the dataset list.")
            return dict(value)
