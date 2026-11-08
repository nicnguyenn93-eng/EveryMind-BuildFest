"""Same-origin, loopback-only HTTP adapter for Netra's frontend."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import tomllib
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

import analysis
from report import DEFAULT_MODEL
from censored_comment_evidence import INPUT_POLICY, build_censored_comment_evidence
from report_service import generate_report, ReportServiceError
from .store import DatasetError, DatasetStore, StaleDatasetError

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 25 * 1024 * 1024


def local_key(root):
    """Credentials remain on the server; never return them through HTTP."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        return tomllib.loads((root / "gemini_secrets.toml").read_text()).get("GEMINI_API_KEY")
    except (OSError, ValueError):
        return None


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    audience: Literal["All respondents", "Students", "Known non-students", "School staff", "Caregiver/parent", "Community member"] = "All respondents"
    expected_dataset_key: str
    use_llm: StrictBool = True
    input_policy: Literal["censored_comments_v1"] | None = None


def create_app(*, private_root=None, store=None, reporter=generate_report, key_loader=local_key):
    root = Path(private_root or ROOT / "private_data").resolve()
    datasets = store or DatasetStore(root)

    @asynccontextmanager
    async def lifespan(app):
        yield
        datasets.close()

    app = FastAPI(title="EveryMind local API", version="1.0", lifespan=lifespan)
    app.state.datasets = datasets
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def boundary(request, call_next):
        # Custom header prevents cross-site HTML forms; Origin check prevents a
        # different site from using this local server's configured provider key.
        if request.method == "POST":
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if request.headers.get("x-everymind-request") != "1" or (origin and origin != expected):
                return JSONResponse({"detail": "Use the local EveryMind page to make this request."}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > MAX_UPLOAD + 65536):
                return JSONResponse({"detail": "File exceeds the 25 MB upload limit."}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(DatasetError)
    async def dataset_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409 if isinstance(error, StaleDatasetError) else 400)

    @app.exception_handler(ReportServiceError)
    async def report_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/api/status")
    def status():
        return dict(schema_version="everymind.web.v1", ai_configured=bool(key_loader(root)),
                    model=DEFAULT_MODEL, input_policy=INPUT_POLICY, max_upload_bytes=MAX_UPLOAD, audiences=sorted(analysis.AUDIENCES))

    @app.get("/api/datasets")
    def list_datasets():
        return dict(datasets=datasets.discover())

    @app.post("/api/uploads", status_code=202)
    async def upload(file: UploadFile):
        try:
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in (".csv", ".xlsx"):
                raise HTTPException(400, "Choose a raw survey .xlsx or UTF-8 .csv export.")
            payload = bytearray()
            while chunk := await file.read(1024 * 1024):
                payload.extend(chunk)
                if len(payload) > MAX_UPLOAD:
                    raise HTTPException(413, "File exceeds the 25 MB upload limit.")
            if not payload:
                raise HTTPException(400, "Choose a nonempty survey export.")
            return dict(job_id=datasets.submit(bytes(payload), suffix), status="processing")
        finally:
            await file.close()

    @app.get("/api/jobs/{token}")
    def job(token: str):
        return datasets.job(token)

    @app.get("/api/datasets/{identifier}/dashboard")
    def dashboard(identifier: str, audience: str = "All respondents"):
        if audience not in analysis.AUDIENCES:
            raise HTTPException(400, "Choose a supported audience.")
        return datasets.dashboard(identifier, audience)

    @app.post("/api/reports")
    def report(request: ReportRequest):
        if request.input_policy != INPUT_POLICY:
            raise HTTPException(409, "Report inputs now include censored written responses. Reload the page before generating a report.")
        export = datasets.resolve(request.dataset_id)
        result = reporter(export.path, request.audience,
            expected_dataset_key=request.expected_dataset_key, use_llm=request.use_llm, include_censored_comments=True,
            api_key=key_loader(root), model=DEFAULT_MODEL, retries=2)
        cited = set(result.get("evidence_ids", []))
        for item in result.get("summary", []) + result.get("proposed_recommendations", []):
            cited.update(item.get("evidence_ids", []))
        # Only the cited censored wording reaches the action cards. The dashboard
        # stays aggregate-only and no source IDs or original-comment sidecars enter it.
        fields = ("comment_evidence_id", "source_field", "language", "censored_text", "review_status")
        comments = [{name: item[name] for name in fields}
                    for item in build_censored_comment_evidence(export, request.audience)
                    if item["comment_evidence_id"] in cited]
        return dict(scope="All surveyed locations · " + request.audience, report=result,
                    cited_comment_evidence=comments)

    # Only public frontend assets are served. No repository/private-data mount.
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    return app
