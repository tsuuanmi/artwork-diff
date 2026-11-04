"""Generate a self-contained English-language HTML review report.

The embedded PDF page previews are rasterized only for visualization. Changes
are detected by object comparison in core.py, not by pixel subtraction.
"""
from __future__ import annotations

import base64
import html
import io
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium


def preview(pdf_path: Path, page_index: int, max_width: int = 1250) -> str:
    """Return a JPEG data URI for a PDF page."""
    with pdfium.PdfDocument(str(pdf_path)) as document:
        page = document[page_index]
        scale = min(2.0, max_width / max(page.get_width(), 1))
        image = page.render(scale=scale).to_pil().convert("RGB")
        output = io.BytesIO()
        image.save(output, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def boxed_rect(bbox: list[float] | None, finding_id: int) -> str:
    """Build an SVG outline in the original PDF page coordinate system."""
    if not bbox:
        return ""
    x0, y0, x1, y1 = bbox
    padding = 3.5
    x, y = x0 - padding, y0 - padding
    width = max(x1 - x0 + 2 * padding, 8)
    height = max(y1 - y0 + 2 * padding, 8)
    return (
        f'<rect class="mark m{finding_id}" x="{x:.3f}" y="{y:.3f}" '
        f'width="{width:.3f}" height="{height:.3f}" rx="1" />'
    )


def _panel(label: str, image: str, width: float, height: float, marks: list[str]) -> str:
    heading = html.escape(label)
    if not image:
        return f'<div class="pane"><h3>{heading}</h3><p>No corresponding page.</p></div>'
    return (
        f'<div class="pane"><h3>{heading}</h3><div class="artwork">'
        f'<img src="{image}" alt="{heading}">'
        f'<svg viewBox="0 0 {width:.5f} {height:.5f}" preserveAspectRatio="none">'
        f'{"".join(marks)}</svg></div></div>'
    )


def render_html(report: dict[str, Any], approved: Path, production: Path, output: Path) -> None:
    """Write a standalone, clickable, side-by-side HTML report."""
    sections: list[str] = []
    for page_index, page in enumerate(report["pages"]):
        width, height = page["size_approved"]
        new_width, new_height = page["size_production"]
        left_image = preview(approved, page_index) if page_index < report["pages_approved"] else ""
        right_image = preview(production, page_index) if page_index < report["pages_production"] else ""
        left_marks: list[str] = []
        right_marks: list[str] = []
        findings: list[str] = []
        for index, difference in enumerate(page["differences"]):
            finding_id = page_index * 100000 + index
            left_marks.append(boxed_rect(difference["bbox_before"], finding_id))
            right_marks.append(boxed_rect(difference["bbox_after"], finding_id))
            category = html.escape(f'{difference["kind"]} / {difference["change"]}')
            description = html.escape(difference["before"] or difference["after"])
            reason = html.escape(difference["reason"])
            fields = html.escape(", ".join(difference["fields"]))
            findings.append(
                f'<li class="finding" id="d{finding_id}" onclick="focusFinding({finding_id})">'
                f'<strong>#{index + 1} {category}</strong> {description}'
                f'<small>{reason} {fields}</small></li>'
            )
        count = len(page["differences"])
        empty = '<li>No differences detected in the supported object types.</li>'
        sections.append(
            f'<section><h2>Page {page_index + 1} - {count} finding(s)</h2>'
            f'<p class="details">Page size (PDF points): '
            f'{width:.2f} x {height:.2f} / {new_width:.2f} x {new_height:.2f}</p>'
            f'<div class="side-by-side">'
            f'{_panel("Customer-approved artwork", left_image, width, height, left_marks)}'
            f'{_panel("Production artwork", right_image, new_width, new_height, right_marks)}'
            f'</div><ol class="findings">{"".join(findings) if findings else empty}</ol></section>'
        )

    title = (
        "Artwork Diff - review required"
        if report["total_differences"]
        else "Artwork Diff - no differences in covered checks"
    )
    page_total = len(report["pages"])
    document = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; background: #f4f6fa; font: 14px/1.5 system-ui,Arial,sans-serif; color: #162033; }}
    header {{ background: #15233a; color: #fff; padding: 18px 4vw; }}
    h1 {{ font-size: 22px; margin: 0; }}
    main {{ max-width: 1500px; margin: auto; padding: 14px 3vw; }}
    .warning {{ padding: 12px 15px; border-left: 4px solid #c77325; background: #fff; margin: 16px 0; }}
    section {{ border: 1px solid #dbe0e9; background: white; padding: 16px; margin: 24px 0; border-radius: 10px; }}
    h2 {{ font-size: 18px; margin: 0; }}
    h3 {{ font-size: 15px; }}
    .details, small {{ color: #5e697a; }}
    .side-by-side {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .artwork {{ position: relative; display: block; width: 100%; box-shadow: 0 1px 7px #bbb; overflow: hidden; }}
    .artwork img {{ width: 100%; display: block; }}
    .artwork svg {{ position: absolute; left: 0; top: 0; width: 100%; height: 100%; pointer-events: none; }}
    .mark {{ fill: rgba(235,25,42,.11); stroke: #ed233e; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
    .mark.selected {{ fill: rgba(255,146,0,.25); stroke: #fb8500; stroke-width: 3; }}
    .findings {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 7px; padding-left: 21px; }}
    .finding {{ cursor: pointer; padding: 8px; border: 1px solid #e5eaf0; border-radius: 7px; }}
    .finding:hover, .finding.selected {{ background: #fff6e6; border-color: #ffb84a; }}
    small {{ display: block; }}
    @media (max-width: 760px) {{ .side-by-side {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header><h1>{title}</h1><div>Findings: {report["total_differences"]} |
    Pages: {page_total} | Geometry tolerance: {report["tolerance_mm"]} mm</div></header>
  <main>
    <div class="warning"><strong>EXPERIMENTAL - not a print-production certification.</strong>
      The comparator currently checks PDF text characters, lines, rectangles, Bezier paths,
      and embedded images. It does not fully inspect spot colors, CMYK/ICC, overprint,
      clipping, outlined text, hidden layers, alternate image encoding, or geometrically
      equivalent vector paths. Zero reported findings does not establish artwork equivalence.
    </div>
    {''.join(sections)}
  </main>
  <script>
    function focusFinding(id) {{
      document.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.m' + id).forEach(el => el.classList.add('selected'));
      const item = document.getElementById('d' + id);
      if (item) {{
        item.classList.add('selected');
        item.closest('section').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}
  </script>
</body>
</html>'''
    output.write_text(document, encoding="utf-8")
