"""Regression tests for low-noise HTML grouping (synthetic artwork only)."""
from pathlib import Path
import tempfile
import unittest

from reportlab.pdfgen.canvas import Canvas

from artwork_diff.cli import run
from artwork_diff.reporting import group_color_changes, group_review_regions


def color_item(kind: str = "text", color_field: str = "color", value=None) -> dict:
    old = (1, .9, 0, .1) if value is None else value
    return {"kind": kind, "change": "modified", "fields": [color_field],
            "old_attrs": {color_field: old},
            "new_attrs": {color_field: (0, 1, 1, 0)},
            "bbox_before": [10, 20, 20, 30],
            "bbox_after": [10, 20, 20, 30]}


def make_pdf(path: Path, label: str) -> None:
    pdf = Canvas(str(path), pagesize=(600, 350))
    pdf.setFont("Helvetica", 22)
    pdf.drawString(60, 160, label)
    pdf.setLineWidth(2)
    pdf.line(60, 100, 500, 100)
    pdf.save()


class HTMLGroupingTests(unittest.TestCase):
    def test_mass_palette_change_is_one_review_group(self):
        diffs = ([color_item("text", "color") for _ in range(208)]
                 + [color_item("curve", "fill_color") for _ in range(238)]
                 + [color_item("rect", "fill_color") for _ in range(82)])
        important, grouped = group_color_changes(diffs)
        self.assertEqual(len(important), 0)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["count"], 528)
        self.assertEqual(grouped[0]["kinds"], {"text": 208, "curve": 238, "rect": 82})
        # A simultaneous text modification is not hidden among paint changes.
        mixed = dict(color_item(), fields=["color", "text"])
        important, grouped = group_color_changes(diffs + [mixed])
        self.assertEqual(len(important), 1)
        self.assertEqual(grouped[0]["count"], 528)

    def test_adjacent_text_glyphs_share_one_region(self):
        sample = []
        for index in range(5):
            sample.append((index, {"kind": "text", "change": "modified",
                                   "bbox_before": [10 + index * 12, 30, 22 + index * 12, 49],
                                   "bbox_after": [10 + index * 12, 30, 22 + index * 12, 49]}))
        regions = group_review_regions(sample)
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0]["members"]), 5)
        sample.append((5, {"kind": "text", "bbox_before": [400, 230, 420, 250], "bbox_after": None}))
        self.assertEqual(len(group_review_regions(sample)), 2)

    def test_html_renders_single_zoom_for_content_region(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            a, b = root / "approved.pdf", root / "production.pdf"
            make_pdf(a, "City Quang Ninh")
            make_pdf(b, "Province Quang Ninh")
            result = run(a, b, root / "out", 0.05, 10)
            self.assertGreater(result["total_differences"], 0)
            html_content = (root / "out" / "report.html").read_text(encoding="utf-8")
            self.assertIn("COMPARISON REPORT", html_content)
            self.assertIn("Focused differences", html_content)
            self.assertIn("City Quang Ninh", html_content)
            self.assertIn("Province Quang Ninh", html_content)
            self.assertIn('class="focus-block"', html_content)


if __name__ == "__main__":
    unittest.main()
