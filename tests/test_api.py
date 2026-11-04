"""HTTP API tests use synthetic PDFs; customer artwork never enters Git."""
from __future__ import annotations

from io import BytesIO
import os
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from artwork_diff.api import app


def sample_pdf(text: str) -> bytes:
    output = BytesIO()
    c = Canvas(output, pagesize=(400, 280))
    c.setFont("Helvetica", 14)
    c.drawString(40, 170, text)
    c.line(40, 130, 350, 130)
    c.save()
    return output.getvalue()


def pdf_files(left: bytes, right: bytes) -> dict:
    return {
        "approved": ("approved.pdf", left, "application/pdf"),
        "production": ("production.pdf", right, "application/pdf"),
    }


class TestAPI(TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.approved = sample_pdf("APPROVED PDF")
        self.changed = sample_pdf("CHANGED PDF")

    def tearDown(self) -> None:
        self.client.close()

    def test_health_and_docs(self) -> None:
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_compare_same_pdf(self) -> None:
        response = self.client.post("/v1/compare", files=pdf_files(self.approved, self.approved))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_differences"], 0)
        self.assertEqual(payload["status"], "NO_DIFFERENCES_IN_COVERED_CHECKS")
        self.assertIn("ink_audit", payload)
        self.assertEqual(payload["approved_file"], "approved.pdf")
        self.assertNotIn("artwork-diff-", payload["approved_file"])

    def test_compare_changed_pdf(self) -> None:
        response = self.client.post("/v1/compare", files=pdf_files(self.approved, self.changed))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["total_differences"], 0)
        self.assertIn("ink_audit", response.json())

    def test_optional_ink_audit(self) -> None:
        response = self.client.post(
            "/v1/compare", files=pdf_files(self.approved, self.changed),
            data={"include_ink_audit": "false"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ink_audit", response.json())

    def test_html_report(self) -> None:
        response = self.client.post("/v1/compare/report", files=pdf_files(self.approved, self.changed))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("<html", response.text)

    def test_upload_validation(self) -> None:
        response = self.client.post("/v1/compare", files=pdf_files(b"not a pdf", self.approved))
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/v1/compare", files=pdf_files(self.approved, self.changed),
                                    data={"tolerance_mm": "-1"})
        self.assertEqual(response.status_code, 422)

    def test_upload_limit(self) -> None:
        with patch("artwork_diff.api.MAX_UPLOAD_BYTES", 10):
            response = self.client.post("/v1/compare", files=pdf_files(self.approved, self.changed))
        self.assertEqual(response.status_code, 413)

    def test_authentication_when_configured(self) -> None:
        with patch.dict(os.environ, {"ARTWORK_DIFF_API_KEY": "local-secret"}):
            self.assertEqual(self.client.post("/v1/compare", files=pdf_files(self.approved, self.changed)).status_code, 401)
            response = self.client.post("/v1/compare", files=pdf_files(self.approved, self.changed),
                                        headers={"X-API-Key": "local-secret"})
            self.assertEqual(response.status_code, 200)
