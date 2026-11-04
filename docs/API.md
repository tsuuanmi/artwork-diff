# Artwork Diff HTTP API

**Status: experimental (v0.3.0).** The API is a stateless wrapper around the same PDF comparison and CMYK/text audit engines as the CLI.

## Setup

~~~sh
uv sync --extra api --extra dev
uv run uvicorn artwork_diff.api:app --host 127.0.0.1 --port 8000
~~~

Open `/docs` for interactive FastAPI Swagger UI and `/openapi.json` for the machine-readable OpenAPI contract.

## Contract

| Endpoint | Request | Response |
| --- | --- | --- |
| `GET /health` | None | `{"status":"ok","service":"artwork-diff"}` |
| `POST /v1/compare` | Multipart: `approved`, `production`, optional `tolerance_mm`, `match_radius_pt`, `include_ink_audit` | JSON with `status`, `total_differences`, `pages[]`, `limitations`, and optional `ink_audit` |
| `POST /v1/compare/report` | Multipart: `approved`, `production`, optional `tolerance_mm`, `match_radius_pt` | `text/html` self-contained side-by-side visual review report |

Both PDF uploads are required. Default numeric thresholds: `tolerance_mm=0.05`, `match_radius_pt=10`; allowed ranges `(0, 5]` mm and `(0, 100]` pt, respectively. `include_ink_audit=true` is the default for JSON comparisons.

A comparison mismatch is a successful execution and therefore HTTP **200** with `status=REVIEW_REQUIRED`, not HTTP 409/422. Invalid PDFs return HTTP 422, too-large uploads HTTP 413, missing/invalid API keys HTTP 401, and invalid parameters HTTP 422.

## Examples

~~~sh
curl -X POST 'http://127.0.0.1:8000/v1/compare' \
  -F 'approved=@approved.pdf;type=application/pdf' \
  -F 'production=@production.pdf;type=application/pdf' \
  -F 'include_ink_audit=true' \
  -o diff.json
~~~

~~~sh
curl -X POST 'http://127.0.0.1:8000/v1/compare/report' \
  -F 'approved=@approved.pdf;type=application/pdf' \
  -F 'production=@production.pdf;type=application/pdf' \
  -o report.html
~~~

## Operational and security notes

- The API processes inputs in a per-request temporary directory, which is removed after the response is constructed. HTML previews contain embedded base64 images, so the **HTML output itself includes artwork** and must be protected as confidential.
- Upload cap: 25 MiB **per PDF**, page cap: 50 **per PDF**. Limits are defaults of this prototype, not prepress standards.
- The API has no authentication unless `ARTWORK_DIFF_API_KEY` is configured. If configured, supply `X-API-Key` for POST endpoints; health and docs remain public. Keep the service bound to `127.0.0.1` for local development.
- Do not expose directly to public internet; use TLS, stronger auth/access control, process limits, observability and rate limiting behind a trusted reverse proxy.
- Never interpret zero findings as proof that two artwork PDFs are print-equivalent. Native `.ai`, outline-text recovery, complete ICC/spot-color separation and actual clipping geometry comparison are not implemented.
