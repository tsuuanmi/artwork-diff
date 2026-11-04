"""HTTP API for vector-aware PDF comparison.

Uploads are bounded, processed inside a temporary directory, and deleted after
responding. Run behind an authenticated HTTPS reverse proxy in production.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
import pypdfium2 as pdfium
from starlette.concurrency import run_in_threadpool

from .cli import run
from .ink_audit import audit

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PAGES = 50
CHUNK_SIZE = 1024 * 1024

app = FastAPI(
    title="Artwork Diff API",
    description=(
        "Experimental object-level PDF comparison. Results are not a print-production "
        "certification; human prepress review is required."
    ),
    version="0.4.0",
)


def _authorize(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("ARTWORK_DIFF_API_KEY")
    if expected and not secrets.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _public_name(upload: UploadFile, fallback: str) -> str:
    return (upload.filename or fallback).replace("\\", "/").split("/")[-1] or fallback


async def _save_pdf(upload: UploadFile, destination: Path) -> None:
    size = 0
    header = bytearray()
    try:
        with destination.open("wb") as stream:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 25 MiB upload limit")
                if len(header) < 1024:
                    header.extend(chunk[: 1024 - len(header)])
                stream.write(chunk)
        if b"%PDF-" not in bytes(header):
            raise HTTPException(status_code=422, detail="Upload does not contain a PDF header")
        try:
            with pdfium.PdfDocument(str(destination)) as document:
                if not 1 <= len(document) <= MAX_PAGES:
                    raise HTTPException(status_code=422, detail="PDF must contain 1-50 pages")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid or unsupported PDF") from exc
    finally:
        await upload.close()


@asynccontextmanager
async def _uploaded_pair(approved: UploadFile, production: UploadFile) -> AsyncIterator[tuple[Path, Path, Path]]:
    with TemporaryDirectory(prefix="artwork-diff-") as directory:
        root = Path(directory)
        before = root / "approved.pdf"
        after = root / "production.pdf"
        await _save_pdf(approved, before)
        await _save_pdf(production, after)
        yield before, after, root / "report"


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "artwork-diff"}


@app.post("/v1/compare/json", dependencies=[Depends(_authorize)], tags=["compare"])
async def compare_pdfs(
    approved: Annotated[UploadFile, File(description="Customer-approved PDF")],
    production: Annotated[UploadFile, File(description="Production PDF")],
    tolerance_mm: Annotated[float, Form(gt=0, le=5)] = 0.05,
    match_radius_pt: Annotated[float, Form(gt=0, le=100)] = 10.0,
    include_ink_audit: Annotated[bool, Form()] = True,
) -> dict:
    """Return object differences and, optionally, grouped ink/content findings."""
    async with _uploaded_pair(approved, production) as (before, after, output):
        result = await run_in_threadpool(run, before, after, output, tolerance_mm, match_radius_pt)
        result["approved_file"] = _public_name(approved, "approved.pdf")
        result["production_file"] = _public_name(production, "production.pdf")
        if include_ink_audit:
            result["ink_audit"] = await run_in_threadpool(audit, before, after)
        return result


@app.post("/v1/compare", dependencies=[Depends(_authorize)], response_class=HTMLResponse, tags=["compare"])
@app.post("/v1/compare/report", dependencies=[Depends(_authorize)], response_class=HTMLResponse, tags=["compare"], include_in_schema=False)
async def compare_report(
    approved: Annotated[UploadFile, File(description="Customer-approved PDF")],
    production: Annotated[UploadFile, File(description="Production PDF")],
    tolerance_mm: Annotated[float, Form(gt=0, le=5)] = 0.05,
    match_radius_pt: Annotated[float, Form(gt=0, le=100)] = 10.0,
) -> HTMLResponse:
    """Return a self-contained HTML review report without persisting uploads."""
    async with _uploaded_pair(approved, production) as (before, after, output):
        await run_in_threadpool(run, before, after, output, tolerance_mm, match_radius_pt)
        return HTMLResponse((output / "report.html").read_text(encoding="utf-8"))
