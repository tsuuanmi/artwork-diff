"""Extract and compare text, vector shapes, and images from PDF documents.

This module intentionally operates on PDF objects rather than rendered pixels.
The matching heuristic is experimental and does not verify prepress safety.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

import numpy as np
import pdfplumber
from scipy.spatial import cKDTree

PT_PER_MM = 72.0 / 25.4


def tidy(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (tuple, list)):
        return tuple(tidy(x) for x in value)
    return value


def flat_numbers(value: Any) -> tuple[float, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(k for x in value for k in flat_numbers(x))
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return (float(value),)
    return ()


def normalize_font(name: str) -> str:
    # Remove common PDF subset prefix (e.g. ABCDEF+MyFont), not the actual font family.
    return re.sub(r"^[A-Z]{6}\+", "", str(name or ""))


def norm_color(col: Any) -> Any:
    if isinstance(col, (tuple, list)):
        return tuple(round(float(x), 5) if isinstance(x, (int, float)) else str(x) for x in col)
    if isinstance(col, (int, float)):
        return (round(float(col), 5),)
    return str(col)


@dataclass
class Obj:
    kind: str
    bbox: tuple[float, float, float, float]
    path_ops: tuple[str, ...]
    shape: tuple[float, ...]
    attrs: dict[str, Any]
    label: str

    def center(self) -> tuple[float, float]:
        a, b, c, d = self.bbox
        return ((a + c) * 0.5, (b + d) * 0.5)


def item_from_raw(kind: str, raw: dict[str, Any]) -> Obj:
    box = tuple(float(raw[k]) for k in ("x0", "top", "x1", "bottom"))
    if kind == "text":
        shape = box
        attrs = {
            "text": raw.get("text", ""), "font": normalize_font(raw.get("fontname", "")),
            "size": round(float(raw.get("size", 0)), 5),
            "color": norm_color(raw.get("non_stroking_color")),
            "matrix": tuple(round(float(x), 4) for x in raw.get("matrix", (1, 0, 0, 1))[:4]),
        }
        label = f"Character {raw.get('text')!r}"
        return Obj(kind, box, (), shape, attrs, label)
    if kind == "image":
        stream = raw.get("stream")
        try:
            # Compare decoded image samples, not PDF object numbers. Different encodings
            # of the same picture can still produce false positives.
            payload = stream.get_data() if stream is not None else b""
            digest = hashlib.sha256(payload).hexdigest()
        except Exception:
            digest = "UNREADABLE"
        shape = box
        attrs = {"sha256_decoded": digest, "srcsize": tidy(raw.get("srcsize")),
                 "colorspace": str(raw.get("colorspace")), "bits": raw.get("bits")}
        return Obj(kind, box, (), shape, attrs, "Embedded PDF image")
    path = raw.get("path") or []
    # Keep exact Bezier control points (not raster pixels); PDF exporters may emit
    # semantically identical artwork using different path descriptions.
    shape = flat_numbers(path) if path else flat_numbers(raw.get("pts", []))
    ops = tuple(str(x[0]) for x in path)
    attrs = {
        "stroke": bool(raw.get("stroke", False)), "fill": bool(raw.get("fill", False)),
        "linewidth": round(float(raw.get("linewidth") or 0), 5) if raw.get("stroke") else None,
        "stroke_color": norm_color(raw.get("stroking_color")) if raw.get("stroke") else None,
        "fill_color": norm_color(raw.get("non_stroking_color")) if raw.get("fill") else None,
        "dash": str(raw.get("dash", "")) if raw.get("stroke") else None,
    }
    shape_names = {"line": "Line", "rect": "Rectangle", "curve": "Vector path / Bezier curve"}
    return Obj(kind, box, ops, shape, attrs, shape_names[kind])


def extract(pdf_path: Path) -> list[dict[str, Any]]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            items = []
            for kind, prop in (("text", "chars"), ("line", "lines"),
                               ("rect", "rects"), ("curve", "curves"),
                               ("image", "images")):
                for raw in getattr(p, prop):
                    items.append(item_from_raw(kind, raw))
            pages.append({"width": float(p.width), "height": float(p.height), "items": items})
    return pages


def geom_diff(a: Obj, b: Obj) -> float:
    if len(a.shape) != len(b.shape) or a.path_ops != b.path_ops:
        return float("inf")
    vals = [abs(x-y) for x, y in zip(a.shape, b.shape)]
    return max(vals) if vals else max(abs(x-y) for x, y in zip(a.bbox, b.bbox))


def style_diff(a: Obj, b: Obj, col_eps: float = 0.003) -> list[str]:
    changed = []
    for key in sorted(set(a.attrs) | set(b.attrs)):
        x, y = a.attrs.get(key), b.attrs.get(key)
        if x == y:
            continue
        # Color tolerance across export stages, without suppressing real changes.
        if "color" in key and isinstance(x, tuple) and isinstance(y, tuple):
            if len(x) == len(y) and all(isinstance(v, (int, float)) for v in x+y):
                if max(abs(u-v) for u, v in zip(x, y)) <= col_eps:
                    continue
        if key in ("size", "linewidth") and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if abs(x-y) <= 0.01:
                continue
        # Illustrator and other PDF exporters can re-subset an identical font
        # and change the text matrix by sub-pixel rounding (e.g. 28.5744
        # vs 28.5742), without a visible or intended production change.
        # Compare matrix numerically, not as a serialized tuple.
        if key == "matrix" and isinstance(x, (tuple, list)) and isinstance(y, (tuple, list)):
            if len(x) == len(y) and all(isinstance(v, (int, float)) for v in tuple(x) + tuple(y)):
                if all(abs(u-v) <= 0.002 for u,v in zip(x,y)):
                    continue
        changed.append(key)
    return changed


def in_range(a: Obj, b: Obj, radius: float) -> bool:
    return np.linalg.norm(np.array(a.center()) - np.array(b.center())) <= radius


def compare_page(left: list[Obj], right: list[Obj], tol_pt: float, match_radius: float) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()
    for kind in ("text", "line", "rect", "curve", "image"):
        ia = [i for i, obj in enumerate(left) if obj.kind == kind]
        ib = [j for j, obj in enumerate(right) if obj.kind == kind]
        if not ia and not ib:
            continue
        coords_b = [right[j].center() for j in ib]
        tree = cKDTree(coords_b) if coords_b else None
        # First pass: same geometry + metadata, regardless of stream/object order.
        for i in ia:
            a = left[i]
            candidates = [] if tree is None else tree.query_ball_point(a.center(), tol_pt * 2 + 0.02)
            for ix in candidates:
                j = ib[ix]
                if j in used_b:
                    continue
                if geom_diff(a, right[j]) <= tol_pt and not style_diff(a, right[j]):
                    used_a.add(i)
                    used_b.add(j)
                    break
        # Second pass: pair close changes, but do not treat distant objects as edits.
        candidates: list[tuple[float, int, int]] = []
        for i in ia:
            if i in used_a or tree is None:
                continue
            a = left[i]
            for ix in tree.query_ball_point(a.center(), match_radius):
                j = ib[ix]
                if j in used_b:
                    continue
                b = right[j]
                dist = float(np.linalg.norm(np.array(a.center()) - np.array(b.center())))
                gd = geom_diff(a, b)
                # Only pair different path topologies when their boxes are very close.
                if not np.isfinite(gd) and dist > tol_pt * 2:
                    continue
                fields = style_diff(a, b)
                penalty = min(gd, 8.0) if np.isfinite(gd) else 12.0
                score = dist * 1.5 + penalty + (2.0 if fields else 0.0)
                candidates.append((score, i, j))
        for _, i, j in sorted(candidates):
            if i in used_a or j in used_b:
                continue
            a, b = left[i], right[j]
            used_a.add(i)
            used_b.add(j)
            gd = geom_diff(a, b)
            changed = style_diff(a, b)
            if gd <= tol_pt and not changed:
                continue
            reason = "geometry + attributes" if gd > tol_pt and changed else "geometry" if gd > tol_pt else "attributes"
            if "text" in changed:
                reason = "text changed" if len(changed) == 1 and gd <= tol_pt else reason + ", text changed"
            diffs.append({"kind": kind, "change": "modified", "reason": reason,
                          "fields": changed, "bbox_before": list(a.bbox), "bbox_after": list(b.bbox),
                          "before": a.label, "after": b.label,
                          "old_attrs": a.attrs, "new_attrs": b.attrs})
        for i in ia:
            if i not in used_a:
                a = left[i]
                diffs.append({"kind": kind, "change": "removed", "reason": "Object missing in production",
                              "fields": [], "bbox_before": list(a.bbox), "bbox_after": None,
                              "before": a.label, "after": "", "old_attrs": a.attrs, "new_attrs": None})
        for j in ib:
            if j not in used_b:
                b = right[j]
                diffs.append({"kind": kind, "change": "added", "reason": "Additional production object",
                              "fields": [], "bbox_before": None, "bbox_after": list(b.bbox),
                              "before": "", "after": b.label, "old_attrs": None, "new_attrs": b.attrs})
    return diffs


def group_adjacent_text_diffs(diffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent same-line added/removed text characters into readable text runs.

    Keeps individual modified characters and non-text objects separate. This is
    a PRESENTATION grouping, not an assumption about semantic equivalence.
    """
    groups: list[list[dict[str, Any]]] = []
    others: list[dict[str, Any]] = []
    relevant = []
    for d in diffs:
        if d['kind'] == 'text' and d['change'] in ('removed', 'added'):
            box = d['bbox_before'] if d['change']=='removed' else d['bbox_after']
            if box:
                relevant.append(d)
                continue
        others.append(d)
    relevant.sort(key=lambda d: (d['change'],
                                 round((d['bbox_before'] or d['bbox_after'])[1] / 3),
                                 (d['bbox_before'] or d['bbox_after'])[0]))
    for d in relevant:
        rect = d['bbox_before'] or d['bbox_after']
        if groups:
            prev = groups[-1][-1]
            pbox = prev['bbox_before'] or prev['bbox_after']
            if (prev['change'] == d['change'] and
                abs(rect[1]-pbox[1]) <= 1.0 and
                -6.0 <= rect[0]-pbox[2] <= 18.0 and
                d['old_attrs' if d['change']=='removed' else 'new_attrs'].get('font') ==
                prev['old_attrs' if d['change']=='removed' else 'new_attrs'].get('font')):
                groups[-1].append(d)
                continue
        groups.append([d])
    for run in groups:
        if len(run)==1:
            others.append(run[0]); continue
        f=run[0]
        change=f['change']
        attrs_key='old_attrs' if change=='removed' else 'new_attrs'
        box_key='bbox_before' if change=='removed' else 'bbox_after'
        boxes=[x[box_key] for x in run]
        text=''.join(str(x[attrs_key]['text']) for x in run)
        merged=dict(f)
        merged[box_key]=[min(b[0] for b in boxes),min(b[1] for b in boxes),
                         max(b[2] for b in boxes),max(b[3] for b in boxes)]
        if change=='removed':
            merged['before'] = f"Text run {text!r}"
        else:
            merged['after'] = f"Text run {text!r}"
        merged[attrs_key]=dict(f[attrs_key],text=text)
        merged['grouped_character_count']=len(run)
        others.append(merged)
    return others
