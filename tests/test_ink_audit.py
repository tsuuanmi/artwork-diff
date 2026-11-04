"""Synthetic CMYK, text and clipping checks; no customer PDFs in the repo."""
import tempfile
import unittest
from pathlib import Path

from reportlab.lib.colors import CMYKColor
from reportlab.pdfgen.canvas import Canvas

from artwork_diff.ink_audit import audit, active_colors


def generate(path: Path, blue: bool, include_c1=True, clip=False):
    c = Canvas(str(path), pagesize=(600, 350), pageCompression=0)
    c.setFillColor(CMYKColor(100, 90, 0, 10) if blue else CMYKColor(0, 100, 100, 0))
    c.setFont("Helvetica-Bold", 32)
    c.drawString(50, 270, "PRODUCTION ARTWORK")
    c.rect(48, 205, 320, 40, fill=1, stroke=0)
    path_obj = c.beginPath()
    path_obj.moveTo(80, 180)
    path_obj.curveTo(120, 210, 170, 115, 280, 150)
    c.drawPath(path_obj, fill=1, stroke=0)
    if include_c1:
        if clip:
            c.saveState()
            mask = c.beginPath()
            mask.rect(300, 50, 100, 60)
            c.clipPath(mask, stroke=0)
        c.setFont("Helvetica", 26)
        c.drawString(320, 70, "C1")
        if clip:
            c.restoreState()
    c.setStrokeColorCMYK(0, 0, 0, 100)
    c.line(48, 46, 550, 46)
    c.save()


class TestInkAudit(unittest.TestCase):
    def test_cmyk_change_only(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.pdf", Path(folder) / "b.pdf"
            generate(a, blue=True)
            generate(b, blue=False)
            report = audit(a, b)
            self.assertGreater(report["changed_ink_objects"], 10)
            self.assertEqual(report["pages"][0]["missing_text"], [])
            self.assertEqual(report["pages"][0]["missing_vector_count"], 0)
            self.assertTrue(all("CMYK" in c["before"] and "CMYK" in c["after"]
                                for c in report["color_changes"]))

    def test_missing_text_and_clipping_count(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.pdf", Path(folder) / "b.pdf"
            generate(a, blue=False, clip=True)
            generate(b, blue=False, include_c1=False)
            report = audit(a, b)
            self.assertEqual(report["changed_ink_objects"], 0)
            self.assertEqual([item["text"] for item in report["pages"][0]["missing_text"]], ["C1"])
            self.assertTrue(report["pages"][0]["clip_operator_count_changed"])

    def test_identical_file(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.pdf"
            generate(a, blue=False)
            report = audit(a, a)
            self.assertEqual(report["changed_ink_objects"], 0)
            self.assertEqual(report["pages"][0]["missing_text"], [])
            self.assertFalse(report["pages"][0]["clip_operator_count_changed"])

    def test_inactive_fill_is_not_a_color_change(self):
        a = {"stroke": True, "fill": False, "non_stroking_color": (1, 0, 0, 0),
             "stroking_color": (0, 0, 0, 1)}
        b = dict(a, non_stroking_color=(0, 1, 1, 0))
        self.assertEqual(active_colors("line", a), active_colors("line", b))


if __name__ == "__main__":
    unittest.main()
