# Artwork Diff

**Vector-aware comparison of customer-approved and production PDF artwork, via CLI or HTTP API.**

Artwork Diff is an experimental, offline-first Python tool that compares PDF **objects** instead of relying solely on image/pixel comparison. It identifies candidate changes in text, vector geometry, stroke/fill attributes, embedded images, and page size. The optional CMYK/content auditor groups changes to painted colors, text, and preliminary clipping/spot resources.

> **Important:** This project is a review aid, **not certified prepress software**. `0 differences` means only that the supported checks found no differences. Do not automatically release print jobs based on its result.

## Requirements and installation with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) on your workstation (Linux, macOS, or Windows). The project requires **Python 3.11+**; `uv` manages the project's virtual environment without a manual `venv` or `pip install` step.

**Linux/macOS:**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then clone and install the CLI, API, and test dependencies:

```sh
git clone https://github.com/tsuuanmi/artwork-diff.git
cd artwork-diff
uv sync --extra api --extra dev
```

If you only need the CLI, use `uv sync`. `uv run` automatically uses the project environment and keeps it synchronized.

## CLI: compare two PDFs

```sh
uv run artwork-diff "approved.pdf" "production.pdf" --out reports/comparison
```

Open `reports/comparison/report.html` in a browser, or process `reports/comparison/diff.json` programmatically. The CLI exits **0** if it detects no differences in the covered checks and **1** if it detects a difference (not a program crash).

The experimental CMYK and text audit from [PR #1](https://github.com/tsuuanmi/artwork-diff/pull/1) can also be run directly:

```sh
uv run python -m artwork_diff.ink_audit "approved.pdf" "production.pdf" \
  --out reports/ink-audit.json
```

### Reproducible synthetic demo and tests

```sh
uv sync --extra api --extra dev
uv run python scripts/create_demo.py
uv run artwork-diff demo/approved.pdf demo/production.pdf --out demo/output
uv run python -m unittest discover -s tests -v
```

The demo intentionally changes text, line width, fill color, a Bézier control point, and adds a small vector shape. **No customer files are included.**

## HTTP API (FastAPI)

Run locally with the API extra installed:

```sh
uv run uvicorn artwork_diff.api:app --host 127.0.0.1 --port 8000
```

Open the interactive [Swagger/OpenAPI docs](http://127.0.0.1:8000/docs) on your machine. The OpenAPI schema is available at `http://127.0.0.1:8000/openapi.json`.

| Method | Endpoint | Result |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/v1/compare` | **HTML report (default)**, with grouped colors and focused changes |
| `POST` | `/v1/compare/json` | Raw object-level JSON differences and optional ink/content audit |

All comparison endpoints accept `multipart/form-data` fields `approved` and `production` (PDF files), plus optional numeric `tolerance_mm` (default `0.05`) and `match_radius_pt` (default `10`). `/v1/compare/json` additionally accepts `include_ink_audit` (default `true`).

### JSON API example (optional)

```sh
curl -sS -X POST http://127.0.0.1:8000/v1/compare/json \
  -F 'approved=@approved.pdf;type=application/pdf' \
  -F 'production=@production.pdf;type=application/pdf' \
  -F 'include_ink_audit=true' \
  -o comparison.json
```

The response contains `status` (`REVIEW_REQUIRED` or `NO_DIFFERENCES_IN_COVERED_CHECKS`), `total_differences`, per-page `differences`, and `ink_audit` (unless disabled). Differences return **HTTP 200** with `status=REVIEW_REQUIRED`; invalid PDF uploads return HTTP 422 and oversized files return HTTP 413.

### HTML report example

```sh
curl -sS -X POST http://127.0.0.1:8000/v1/compare \
  -F 'approved=@approved.pdf;type=application/pdf' \
  -F 'production=@production.pdf;type=application/pdf' \
  -o comparison.html
```

The generated HTML embeds both page previews, allowing it to be saved and opened later without an active API server. The visual report groups repeated palette replacements into one row and automatically zooms in on content/geometry changes. The raw per-object evidence remains available at `/v1/compare/json`. Use `POST /v1/compare/report` only as a backwards-compatible HTML alias.

### Input validation and deployment safety

- Uploads are checked for a PDF header and a readable PDF structure. Each input is limited to **25 MiB** and **50 pages**.
- Uploaded PDFs and intermediate reports are processed in a temporary directory and deleted after each request; no persistent customer file store is part of this API.
- **By default, no authentication is required:** bind to `127.0.0.1` and do **not** expose this development server publicly.
- For a private deployment, configure `ARTWORK_DIFF_API_KEY` and send `X-API-Key` to the POST endpoints:

```sh
ARTWORK_DIFF_API_KEY='replace-with-a-strong-secret' \
  uv run uvicorn artwork_diff.api:app --host 127.0.0.1 --port 8000

curl -sS -X POST http://127.0.0.1:8000/v1/compare \
  -H 'X-API-Key: replace-with-a-strong-secret' \
  -F 'approved=@approved.pdf;type=application/pdf' \
  -F 'production=@production.pdf;type=application/pdf'
```

For remote/internal network use, place the API behind an authenticated HTTPS reverse proxy; add access control, timeouts, rate limiting, and resource isolation. A local API key alone is **not** sufficient hardening for hostile/untrusted PDFs.

## Inputs and detection scope

- Both PDFs should use the same page geometry, artboards, and intended visible layers. Illustrator `.ai` is **not directly supported**: export to PDF with vector content preserved.
- The base comparator checks text characters, coordinates, fonts, lines, rectangles, Bézier commands/control points, colors, embedded image stream identity, page dimensions, and added/removed objects.
- The auxiliary ink auditor checks *active* stroke/fill colors (including CMYK components), character additions/removals, geometry with coordinate tolerance, and preliminarily inspects page-level spot-color resources, overprint fields, and clipping-operator counts.
- Neither engine guarantees equivalence of re-encoded Bézier paths, text converted to outlines, clipped/hidden artwork, nested transparency, ICC profiles, Pantone/spot separations, overprint behavior, or print-ready files. Manual human prepress sign-off remains essential.

## Project structure

```text
src/artwork_diff/core.py       PDF object extraction and matching
src/artwork_diff/cli.py        CLI and JSON/HTML report orchestration
src/artwork_diff/reporting.py  Self-contained grouped HTML report
src/artwork_diff/ink_audit.py  CMYK/text audit and spot/clipping metadata
src/artwork_diff/api.py        FastAPI application (optional API extra)
tests/                         Synthetic regression and API tests
scripts/create_demo.py        Generates synthetic PDF samples
docs/OPEN_SOURCE_AUDIT.md     Review of reusable open-source libraries
docs/CMYK_CONTENT_AUDIT.md    Current CMYK/content audit technical scope
```

## Development and open source

This project reuses [pdfplumber](https://github.com/jsvine/pdfplumber), [PDFium/pypdfium2](https://github.com/pypdfium2-team/pypdfium2), and other standard Python libraries. See [the open-source reuse audit](docs/OPEN_SOURCE_AUDIT.md).

The code is licensed under [MIT](LICENSE); dependencies have their own licenses. **Never commit actual customer designs to this public repo.**