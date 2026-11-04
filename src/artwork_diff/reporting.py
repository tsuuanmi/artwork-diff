"""Generate a self-contained English-language HTML review report.

The embedded PDF page previews are rasterized only for visualization. Changes
are detected by object comparison in core.py, not by pixel subtraction.
"""
from __future__ import annotations

import base64
from collections import defaultdict, Counter
import html
import io
import json
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pdfplumber
from PIL import ImageDraw


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



INK_FIELDS = frozenset(("color", "fill_color", "stroke_color"))


def _as_color(value: Any) -> str:
    if isinstance(value, (tuple, list)) and all(isinstance(x, (int, float)) for x in value):
        if len(value) == 4:
            return "CMYK " + " ".join(f"{float(x)*100:.0f}%" for x in value)
        if len(value) == 3:
            return "RGB " + " ".join(f"{float(x)*100:.0f}%" for x in value)
        if len(value) == 1:
            return f"Gray {float(value[0]):.3f}"
    return str(value)


def _palette_pair(diff: dict[str, Any]) -> tuple[str, str] | None:
    """Only group purely color-only edits, never mixed text/geometry changes."""
    if diff.get("change") != "modified":
        return None
    fields = set(diff.get("fields") or ())
    if not fields or not fields.issubset(INK_FIELDS):
        return None
    old, new = diff.get("old_attrs") or {}, diff.get("new_attrs") or {}
    pairs = {(_as_color(old.get(k)), _as_color(new.get(k))) for k in fields}
    return next(iter(pairs)) if len(pairs) == 1 else None


def group_color_changes(differences: list[dict[str, Any]]) -> tuple[list, list]:
    """Keep raw diffs unchanged; group repeated ink-only changes for the UI."""
    groups = defaultdict(list)
    individual = []
    for index, diff in enumerate(differences):
        pair = _palette_pair(diff)
        if pair is None:
            individual.append((index, diff))
        else:
            groups[pair].append((index, diff))
    summaries = []
    for pair, members in sorted(groups.items(), key=lambda entry: -len(entry[1])):
        summaries.append({"before": pair[0], "after": pair[1],
                          "count": len(members), "members": members,
                          "kinds": dict(Counter(d.get("kind", "unknown") for _, d in members))})
    return individual, summaries


def _bounds(boxes: list[tuple[float, float, float, float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _near(a: list[float], b: list[float], gap: float = 16.0) -> bool:
    return (a[0] <= b[2] + gap and b[0] <= a[2] + gap
            and a[1] <= b[3] + gap and b[1] <= a[3] + gap)


def group_review_regions(differences: list[tuple[int, dict[str, Any]]]) -> list[dict]:
    """Coalesce nearby non-ink differences into zoomable review regions."""
    regions = []
    for index, d in differences:
        boxes = [tuple(d[k]) for k in ("bbox_before", "bbox_after") if d.get(k)]
        regions.append({"bbox": _bounds(boxes) if boxes else None, "members": [(index, d)]})
    combined = True
    while combined:
        combined = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i]["bbox"], regions[j]["bbox"]
                if a and b and _near(a, b):
                    regions[i]["bbox"] = _bounds([a, b])
                    regions[i]["members"].extend(regions.pop(j)["members"])
                    combined = True
                    break
            if combined:
                break
    return sorted(regions, key=lambda r: ((r["bbox"] or [0, 0])[1], (r["bbox"] or [0, 0])[0]))


def _crop_preview(pdf_path: Path, page_index: int, bbox: list[float]) -> str:
    """High-resolution region-only PDFium rendering for human review."""
    with pdfium.PdfDocument(str(pdf_path)) as document:
        page = document[page_index]
        pw, ph = float(page.get_width()), float(page.get_height())
        dx = max(28.0, min(95.0, (bbox[2] - bbox[0]) * 0.13))
        dy = max(30.0, min(85.0, (bbox[3] - bbox[1]) * 1.2))
        x0, y0 = max(0, bbox[0] - dx), max(0, bbox[1] - dy)
        x1, y1 = min(pw, bbox[2] + dx), min(ph, bbox[3] + dy)
        scale = min(3.0, max(1.0, 1300.0 / max(x1 - x0, 1.0)))
        img = page.render(scale=scale, crop=(x0, ph - y1, pw - x1, y0)).to_pil().convert("RGB")
        rect = [(bbox[0] - x0) * scale, (bbox[1] - y0) * scale,
                max((bbox[2] - x0) * scale, (bbox[0] - x0) * scale + 6),
                max((bbox[3] - y0) * scale, (bbox[1] - y0) * scale + 6)]
        ImageDraw.Draw(img).rectangle(rect, outline="#e23d49", width=3)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=91, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _context_text(pdf_path: Path, page_index: int, bbox: list[float]) -> str:
    """Best-effort line text from PDF glyphs; never used for matching."""
    try:
        with pdfplumber.open(pdf_path) as doc:
            chars = [c for c in doc.pages[page_index].chars
                     if c["top"] < bbox[3] + 4 and c["bottom"] > bbox[1] - 4
                     and c["x0"] < bbox[2] + 4 and c["x1"] > bbox[0] - 4]
        chars.sort(key=lambda c: (round(c["top"] / 3), c["x0"]))
        return "".join(str(c.get("text", "")) for c in chars).strip()[:180]
    except Exception:
        return ""


def _mark(bbox: list[float] | None, css: str) -> str:
    if not bbox:
        return ""
    x0, y0, x1, y1 = bbox
    return (f'<rect class="mark {css}" x="{x0 - 3.5:.3f}" y="{y0 - 3.5:.3f}" '
            f'width="{max(x1-x0+7, 8):.3f}" height="{max(y1-y0+7, 8):.3f}" rx="1" />')


def _zoom_card(label: str, data_uri: str, text: str) -> str:
    return (f'<div class="pane"><h3>{html.escape(label)}</h3>'
            f'<div class="focus-artwork"><img src="{data_uri}" alt="Focused artwork comparison"></div>'
            f'<p class="quote">{html.escape(text) if text else "Inspect outlined region"}</p></div>')


def render_html(report: dict[str, Any], approved: Path, production: Path, output: Path) -> None:
    """Produce a clean comparison sheet; raw findings stay in diff.json.

    Repeated pure-ink edits become one selectable palette row. Text/vector
    changes are grouped by nearby location and displayed as zoomed crops.
    """
    sections = []
    palette_total = painted_total = region_total = 0
    for page_index, page in enumerate(report["pages"]):
        old_w, old_h = page["size_approved"]
        new_w, new_h = page["size_production"]
        old_preview = preview(approved, page_index) if page_index < report["pages_approved"] else ""
        new_preview = preview(production, page_index) if page_index < report["pages_production"] else ""
        findings = page["differences"]
        individual, palette = group_color_changes(findings)
        regions = group_review_regions(individual)
        palette_total += len(palette)
        painted_total += sum(g["count"] for g in palette)
        region_total += len(regions)
        marks_before, marks_after, palette_cards, zoom_cards = [], [], [], []
        for index, group in enumerate(palette):
            css = f"p{page_index}c{index}"
            kinds = ", ".join(f"{k}: {v}" for k, v in sorted(group["kinds"].items()))
            for _, item in group["members"]:
                marks_before.append(_mark(item.get("bbox_before"), f"ink-mark {css}"))
                marks_after.append(_mark(item.get("bbox_after"), f"ink-mark {css}"))
            palette_cards.append(
                f'<article class="palette-row"><div><strong>Ink replacement {index+1}</strong>'
                f'<div class="palette-value">{html.escape(group["before"])} <span>→</span> '
                f'{html.escape(group["after"])}</div>'
                f'<small>{group["count"]} painted objects · {html.escape(kinds)}</small></div>'
                f'<button type="button" aria-pressed="false" onclick="togglePalette(this,&#39;{css}&#39;)">'
                f'Highlight affected objects</button></article>')
        for zone_index, zone in enumerate(regions):
            bounds = zone["bbox"]
            label = ("Content difference" if all(d.get("kind") == "text" for _, d in zone["members"])
                     else "Vector / layout difference")
            if not bounds or page_index >= min(report["pages_approved"], report["pages_production"]):
                zoom_cards.append(f'<p class="muted">Page/object added or removed. Inspect raw JSON.</p>')
                continue
            marks_before.append(_mark(bounds, "review-mark"))
            marks_after.append(_mark(bounds, "review-mark"))
            old_detail = _crop_preview(approved, page_index, bounds)
            new_detail = _crop_preview(production, page_index, bounds)
            old_text = _context_text(approved, page_index, bounds) if label == "Content difference" else ""
            new_text = _context_text(production, page_index, bounds) if label == "Content difference" else ""
            zoom_cards.append(
                f'<article class="focus-block"><h4><span class="num">{zone_index+1:02}</span> '
                f'{html.escape(label)} · {len(zone["members"])} underlying object findings</h4>'
                f'<div class="focus-grid">'
                f'{_zoom_card("APPROVED | Reference", old_detail, old_text)}'
                f'{_zoom_card("PRODUCTION | Comparison", new_detail, new_text)}'
                f'</div></article>')
        palette_block = "".join(palette_cards) or '<p class="muted">No isolated paint-color changes detected.</p>'
        zoom_block = "".join(zoom_cards) or '<p class="muted">No individual content or geometry changes detected.</p>'
        sections.append(
            f'<section><div class="section-head"><h2>PAGE {page_index+1} <span>| Overview</span></h2>'
            f'<small>{len(regions)} review regions · {len(palette)} palette groups · {len(findings)} raw findings</small></div>'
            f'<div class="overview-grid">'
            f'{_panel("APPROVED | Reference artwork", old_preview, old_w, old_h, marks_before)}'
            f'{_panel("PRODUCTION | Compared artwork", new_preview, new_w, new_h, marks_after)}</div>'
            f'<div class="section-head"><h2>COLOR <span>| Grouped ink changes</span></h2></div>'
            f'<div class="palette">{palette_block}</div>'
            f'<div class="section-head"><h2>CONTENT &amp; GEOMETRY <span>| Focused differences</span></h2></div>'
            f'{zoom_block}</section>')
    title = "Artwork Diff | Comparison report"
    old_name = html.escape(Path(str(report.get("approved_file", approved.name))).name)
    new_name = html.escape(Path(str(report.get("production_file", production.name))).name)
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
:root {{ color-scheme:light; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#15181d; color:#172334; font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1280px; min-height:90vh; margin:22px auto; padding:26px 30px 35px; background:#f8f9fc; box-shadow:0 0 26px #0005; }}
h1 {{ font-size:22px; letter-spacing:.03em; font-weight:820; margin:0 0 3px; }}
.header-line {{ font-size:12px; color:#596477; margin:4px 0; }}
h2 {{ font-size:17px; font-weight:800; margin:0; }}
h2 span {{ font-weight:600; color:#4b5767; }}
h3 {{ margin:0 0 8px; font-size:11px; letter-spacing:.015em; font-weight:800; }}
h4 {{ font-size:13px; margin:0 0 10px; }}
section {{ border-top:1px solid #d5d9e2; margin-top:18px; }}
.section-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin:17px 0 12px; }}
small,.muted,.foot {{ font-size:11px; color:#657183; }}
.overview-grid,.focus-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:22px; }}
.pane {{ min-width:0; }}
.artwork,.focus-artwork {{ position:relative; background:white; border:1px solid #d7dce5; }}
.artwork img,.focus-artwork img {{ display:block; width:100%; height:auto; }}
.artwork svg {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
.mark {{ stroke:#e23d49; stroke-width:1.6; fill:transparent; vector-effect:non-scaling-stroke; }}
.ink-mark {{ display:none; stroke:#276dc0; fill:#296fc211; }}
.ink-mark.active-ink {{ display:block; }}
.palette-row {{ background:white; border:1px solid #dde3eb; display:flex; justify-content:space-between; align-items:center; gap:15px; padding:12px 15px; margin-bottom:8px; }}
.palette-row strong {{ font-size:12px; }}
.palette-value {{ font:650 13px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace; margin:2px 0; }}
.palette-value span {{ color:#8b95a3; padding:0 7px; }}
button {{ border:1px solid #b4c0d2; background:white; padding:8px 11px; border-radius:4px; cursor:pointer; font-weight:650; white-space:nowrap; }}
button[aria-pressed="true"] {{ background:#eaf3ff; }}
.focus-block {{ border-top:1px solid #e1e5eb; padding:10px 0 12px; }}
.focus-artwork {{ display:flex; align-items:center; justify-content:center; min-height:120px; }}
.quote {{ font-size:12px; margin:6px 0; color:#35445b; overflow-wrap:anywhere; }}
.num {{ background:#e9edf5; padding:3px 7px; border-radius:4px; margin-right:6px; }}
.foot {{ margin-top:25px; }}
@media(max-width:780px) {{ main {{ margin:0; padding:18px 14px; }} .overview-grid,.focus-grid {{ grid-template-columns:1fr; }} .section-head {{ align-items:flex-start; flex-direction:column; }} .palette-row {{ flex-wrap:wrap; }} }}
</style></head><body><main>
<header><h1>ARTWORK DIFF <span style="color:#a5afc1">|</span> COMPARISON REPORT</h1>
<p class="header-line">{region_total} review regions &nbsp; | &nbsp; {palette_total} ink replacements / {painted_total} affected objects &nbsp; | &nbsp; {report["total_differences"]} raw object findings</p>
<p class="header-line">Reference: {old_name} &nbsp; | &nbsp; Compared: {new_name}</p></header>
{''.join(sections)}
<p class="foot">Object-level PDF evidence. Experimental prepress: full spot/separation, clipping, overprint, ICC and Bezier-equivalence checks are not yet certified. Human sign-off required.</p>
</main><script>
function togglePalette(button, group) {{
 const on = button.getAttribute('aria-pressed') !== 'true';
 button.setAttribute('aria-pressed', String(on));
 button.textContent = on ? 'Hide affected objects' : 'Highlight affected objects';
 document.querySelectorAll('.'+group).forEach(el => el.classList.toggle('active-ink', on));
}}
</script></body></html>'''
    output.write_text(document, encoding="utf-8")
