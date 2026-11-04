"""Comparison orchestration and the command-line interface."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core import PT_PER_MM, compare_page, extract, group_adjacent_text_diffs
from .reporting import render_html


def run(approved: Path, production: Path, out_dir: Path, tol_mm: float, match_radius_pt: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    a_pages, b_pages = extract(approved), extract(production)
    results = []
    total = 0
    for n in range(max(len(a_pages), len(b_pages))):
        a = a_pages[n] if n < len(a_pages) else {"width": 0, "height": 0, "items": []}
        b = b_pages[n] if n < len(b_pages) else {"width": 0, "height": 0, "items": []}
        diffs = group_adjacent_text_diffs(compare_page(a["items"], b["items"], tol_mm * PT_PER_MM, match_radius_pt))
        if abs(a["width"] - b["width"]) > tol_mm * PT_PER_MM or abs(a["height"] - b["height"]) > tol_mm * PT_PER_MM:
            diffs.insert(0, {"kind": "page", "change": "modified", "reason": "Page size changed", "fields": ["size"],
                             "bbox_before": None, "bbox_after": None, "before": "Page size", "after": "Page size",
                             "old_attrs": {"width": a["width"], "height": a["height"]},
                             "new_attrs": {"width": b["width"], "height": b["height"]}})
        total += len(diffs)
        results.append({"page": n + 1, "size_approved": [a["width"], a["height"]],
                        "size_production": [b["width"], b["height"]], "differences": diffs})
    result = {"status": "REVIEW_REQUIRED" if total else "NO_DIFFERENCES_IN_COVERED_CHECKS",
              "total_differences": total, "tolerance_mm": tol_mm, "pages_approved": len(a_pages),
              "pages_production": len(b_pages), "approved_file": str(approved), "production_file": str(production),
              "limitations": ["not certified for production", "no semantic path equivalence", "no outline-text recovery",
                              "no full spot-color/CMYK/overprint check", "no visibility/occlusion analysis", "not ICC color managed"],
              "pages": results}
    (out_dir / "diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    render_html(result, approved, production, out_dir / "report.html")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Experimental object-level PDF artwork comparer")
    p.add_argument("approved", type=Path, help="Customer approved PDF")
    p.add_argument("production", type=Path, help="Production PDF (export AI to PDF first)")
    p.add_argument("--out", type=Path, default=Path("artwork-diff-report"))
    p.add_argument("--tolerance-mm", type=float, default=0.05)
    p.add_argument("--match-radius-pt", type=float, default=10.0)
    args = p.parse_args()
    if args.tolerance_mm <= 0 or args.match_radius_pt <= 0:
        p.error("Tolerances must be positive")
    result = run(args.approved, args.production, args.out, args.tolerance_mm, args.match_radius_pt)
    print(json.dumps({"status": result["status"], "differences": result["total_differences"],
                      "report": str(args.out / "report.html"), "json": str(args.out / "diff.json")}, ensure_ascii=False))
    raise SystemExit(1 if result["total_differences"] else 0)


if __name__ == "__main__":
    main()
