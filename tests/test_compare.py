"""Smoke and regression tests for the PDF artwork comparator."""
import pathlib
import tempfile
import unittest

from reportlab.pdfgen import canvas

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from artwork_diff import run


def art(path, variant=False):
    c = canvas.Canvas(str(path), pagesize=(420, 300), pageCompression=0)
    c.setFont("Helvetica", 16)
    c.drawString(35, 254, "CLIENT APPROVED" if not variant else "CLIENT APPROVFD")
    c.setLineWidth(0.4 if not variant else 0.7)
    c.line(35, 206, 382, 206)
    c.setFillColorRGB(0.15, 0.37 if not variant else 0.52, 0.78)
    c.rect(35, 65, 140, 97, fill=1, stroke=0)
    c.setStrokeColorRGB(.1, .15, .15)
    c.setLineWidth(1.5)
    c.bezier(211, 145, 240, 200, 280 if not variant else 280.9, 115, 349, 152)
    if variant:
        c.circle(363, 96, 2.5, fill=1, stroke=0)
    c.showPage()
    c.save()


class Smoke(unittest.TestCase):
    def test_identical(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            art(d / "a.pdf")
            result = run(d / "a.pdf", d / "a.pdf", d / "report", 0.05, 10)
            self.assertEqual(result["total_differences"], 0)
            self.assertTrue((d / "report" / "report.html").exists())

    def test_subtle_changes(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            art(d / "a.pdf")
            art(d / "b.pdf", True)
            result = run(d / "a.pdf", d / "b.pdf", d / "report", 0.05, 10)
            self.assertGreaterEqual(result["total_differences"], 4)
            kinds = {x["kind"] for x in result["pages"][0]["differences"]}
            self.assertIn("curve", kinds)
            self.assertIn("rect", kinds)
            self.assertIn("text", kinds)
            self.assertTrue((d / "report" / "diff.json").exists())


class Regression(unittest.TestCase):
    def test_font_matrix_roundoff_not_a_difference(self):
        from artwork_diff.core import style_diff, Obj
        a = Obj("text", (10, 20, 20, 30), (), (10, 20, 20, 30),
                {"text": "A", "font": "Test", "size": 29.86,
                 "matrix": (28.5744, 0, 0, 29.8622), "color": (1, 0, 0, 0)}, "A")
        b = Obj("text", (10, 20, 20, 30), (), (10, 20, 20, 30),
                {"text": "A", "font": "Test", "size": 29.86,
                 "matrix": (28.5742, 0, 0, 29.8622), "color": (1, 0, 0, 0)}, "A")
        self.assertEqual(style_diff(a, b), [])
        b.attrs["matrix"] = (28.60, 0, 0, 29.8622)
        self.assertIn("matrix", style_diff(a, b))

    def test_contiguous_removed_characters_grouped(self):
        from artwork_diff.core import group_adjacent_text_diffs
        xs = []
        for i, c in enumerate("ABC"):
            xs.append({"kind": "text", "change": "removed", "reason": "Object missing in production",
                       "fields": [], "bbox_before": [10 + i * 7, 20, 17 + i * 7, 32],
                       "bbox_after": None, "before": f"Character {c!r}", "after": "",
                       "old_attrs": {"text": c, "font": "Helvetica"}, "new_attrs": None})
        merged = group_adjacent_text_diffs(xs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["old_attrs"]["text"], "ABC")


if __name__ == "__main__":
    unittest.main()
