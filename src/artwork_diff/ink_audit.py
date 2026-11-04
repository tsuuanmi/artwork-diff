"""Experimental CMYK/spot-resource and text/vector audit for PDF artwork.

Detection compares extracted PDF objects. This is NOT a certified prepress
comparison: clipping/spot resources are inspected, not fully simulated.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFContentParser
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSKeyword, PSLiteral
from pdfminer.psexceptions import PSEOF

GEOMETRY_QUANTUM_PT = 0.02


def quantize(value: Any, resolution: float) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value) / resolution)
    if isinstance(value, (tuple, list)):
        return tuple(quantize(item, resolution) for item in value)
    return value


def bbox(obj: dict) -> tuple[float, float, float, float]:
    return tuple(float(obj[key]) for key in ("x0", "top", "x1", "bottom"))


def geometry_key(kind: str, obj: dict, resolution: float) -> tuple:
    bounds = quantize(bbox(obj), resolution)
    if kind == "text":
        return (kind, obj.get("text"), bounds)
    return (kind, bounds, quantize(obj.get("path", []), resolution))


def color_label(value: Any) -> str:
    if value is None:
        return "unspecified"
    if isinstance(value, (int, float)):
        value = (value,)
    if not isinstance(value, (tuple, list)):
        return str(value)
    parts = tuple(float(part) for part in value)
    if len(parts) == 4:
        return "CMYK(" + ", ".join(f"{round(part * 100):.0f}%" for part in parts) + ")"
    if len(parts) == 3:
        return "RGB(" + ", ".join(f"{round(part * 100):.0f}%" for part in parts) + ")"
    if len(parts) == 1:
        return f"Gray({parts[0]:.3f})"
    return str(parts)


def active_colors(kind: str, obj: dict) -> dict[str, str]:
    """Ignore stored-but-unused colors on stroke-only or fill-only objects."""
    if kind == "text":
        # Does not fully model the PDF text-rendering-mode state.
        return {"text-fill": color_label(obj.get("non_stroking_color"))}
    result = {}
    if obj.get("fill"):
        result["fill"] = color_label(obj.get("non_stroking_color"))
    if obj.get("stroke"):
        result["stroke"] = color_label(obj.get("stroking_color"))
    return result


def _name(value: Any) -> Any:
    if isinstance(value, PSLiteral):
        return value.name
    if isinstance(value, list):
        return [_name(item) for item in value]
    return str(value)


def inspect_resources(path: Path) -> dict:
    """Inspect *page-level* spot resources, overprint states and clip operators.

    Counts are not equivalent to resolving the complete graphics-state stack or
    the effective intersection of clipping paths. Nested XObject resources are
    not recursively inspected.
    """
    results = {"pages": [], "spot_color_definitions": []}
    with path.open("rb") as source:
        for index, page in enumerate(PDFPage.get_pages(source), 1):
            entry = {"page": index, "clipping_operators": {"W": 0, "W*": 0},
                     "device_cmyk_operators": 0, "spot_color_names": [], "overprint_states": []}
            resources = resolve1(page.resources or {})
            if not isinstance(resources, dict):
                resources = {}
            spaces = resolve1(resources.get("ColorSpace", {}))
            if isinstance(spaces, dict):
                for resource_name, reference in spaces.items():
                    spec = resolve1(reference)
                    if isinstance(spec, list) and len(spec) >= 2:
                        family = _name(spec[0])
                        if family in ("Separation", "DeviceN"):
                            definition = {"resource": str(resource_name), "kind": family,
                                          "name": _name(resolve1(spec[1]))}
                            entry["spot_color_names"].append(definition)
                            results["spot_color_definitions"].append(definition)
            states = resolve1(resources.get("ExtGState", {}))
            if isinstance(states, dict):
                for resource_name, reference in states.items():
                    state = resolve1(reference)
                    if isinstance(state, dict):
                        entry["overprint_states"].append({
                            "resource": str(resource_name), "OP": state.get("OP"),
                            "op": state.get("op"), "OPM": state.get("OPM"),
                            "CA": state.get("CA"), "ca": state.get("ca")})
            parser = PDFContentParser(page.contents)
            while True:
                try:
                    _, item = parser.nextobject()
                except (EOFError, PSEOF):
                    break
                if not isinstance(item, PSKeyword):
                    continue
                operator = (item.name.decode("ascii", errors="replace")
                            if isinstance(item.name, bytes) else str(item.name))
                if operator in ("W", "W*"):
                    entry["clipping_operators"][operator] += 1
                if operator in ("k", "K"):
                    entry["device_cmyk_operators"] += 1
            results["pages"].append(entry)
    return results


def extract_objects(path: Path, resolution: float) -> list[dict]:
    result = []
    with pdfplumber.open(path) as document:
        for page in document.pages:
            groups: dict[tuple, list[dict]] = defaultdict(list)
            for kind, field in (("text", "chars"), ("line", "lines"),
                                ("rectangle", "rects"), ("path", "curves")):
                for raw in getattr(page, field):
                    groups[geometry_key(kind, raw, resolution)].append({
                        "kind": kind, "bbox": bbox(raw),
                        "text": raw.get("text") if kind == "text" else None,
                        "colors": active_colors(kind, raw)})
            result.append({"size": (float(page.width), float(page.height)),
                           "objects": groups})
    return result


def group_text(chars: list[dict]) -> list[dict]:
    if not chars:
        return []
    chars.sort(key=lambda c: (round(c["bbox"][1]), c["bbox"][0]))
    groups = []
    for char in chars:
        if groups:
            last = groups[-1][-1]
            a, b = last["bbox"], char["bbox"]
            if abs(a[1] - b[1]) < 2 and -1 <= b[0] - a[2] <= 16:
                groups[-1].append(char)
                continue
        groups.append([char])
    return [{"text": "".join(c["text"] for c in group),
             "bbox": [min(c["bbox"][0] for c in group),
                      min(c["bbox"][1] for c in group),
                      max(c["bbox"][2] for c in group),
                      max(c["bbox"][3] for c in group)]}
            for group in groups]


def audit(approved: Path, production: Path, resolution: float = GEOMETRY_QUANTUM_PT) -> dict:
    """Pair objects by quantized geometry, then compare active ink and text.

    This heuristic cannot match all equivalent Bezier shapes or normalize
    artboards, and does not catch non-color text-font changes.
    """
    if resolution <= 0:
        raise ValueError("Resolution must be positive")
    approved = Path(approved)
    production = Path(production)
    left = extract_objects(approved, resolution)
    right = extract_objects(production, resolution)
    preflight_left = inspect_resources(approved)
    preflight_right = inspect_resources(production)
    pages = []
    changes = Counter()
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else {"size": (0, 0), "objects": {}}
        b = right[index] if index < len(right) else {"size": (0, 0), "objects": {}}
        p = {"page": index + 1, "missing_text": [], "added_text": [],
             "missing_vector_count": 0, "added_vector_count": 0,
             "page_size_changed": a["size"] != b["size"]}
        for key in a["objects"].keys() | b["objects"].keys():
            aa, bb = a["objects"].get(key, []), b["objects"].get(key, [])
            matched = min(len(aa), len(bb))
            for obj_a, obj_b in zip(aa[:matched], bb[:matched]):
                for channel in obj_a["colors"].keys() | obj_b["colors"].keys():
                    old, new = obj_a["colors"].get(channel), obj_b["colors"].get(channel)
                    if old != new:
                        changes[(index + 1, key[0], channel, old, new)] += 1
            if key[0] == "text":
                p["missing_text"].extend(aa[matched:])
                p["added_text"].extend(bb[matched:])
            else:
                p["missing_vector_count"] += len(aa) - matched
                p["added_vector_count"] += len(bb) - matched
        p["missing_text"] = group_text(p["missing_text"])
        p["added_text"] = group_text(p["added_text"])
        prev_clip = (preflight_left["pages"][index]["clipping_operators"]
                     if index < len(preflight_left["pages"]) else {})
        next_clip = (preflight_right["pages"][index]["clipping_operators"]
                     if index < len(preflight_right["pages"]) else {})
        p["clip_operators_before"] = prev_clip
        p["clip_operators_after"] = next_clip
        p["clip_operator_count_changed"] = prev_clip != next_clip
        pages.append(p)
    color_changes = [
        {"page": k[0], "kind": k[1], "channel": k[2],
         "before": k[3], "after": k[4], "objects": value}
        for k, value in sorted(changes.items(), key=lambda item: (item[0][0], item[0][1], item[0][2]))
    ]
    return {"approved_file": approved.name, "production_file": production.name,
            "geometry_quantization_pt": resolution,
            "changed_ink_objects": sum(changes.values()), "color_changes": color_changes,
            "pages": pages,
            "preflight_approved": preflight_left, "preflight_production": preflight_right,
            "limitations": [
                "Spot definitions and clip operators are inspected only; their visual semantics are not compared",
                "Equivalent paths with different Bezier commands may produce geometry findings",
                "No full color-management, ICC, overprint, transparency or separation simulation",
                "Embedded images, outlined-font equivalence and some font properties are out of scope",
                "Zero findings does not certify print-production equivalence",
            ]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental PDF artwork CMYK/text audit")
    parser.add_argument("approved", type=Path)
    parser.add_argument("production", type=Path)
    parser.add_argument("--out", type=Path, default=Path("ink-audit.json"))
    args = parser.parse_args()
    result = audit(args.approved, args.production)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"active_color_changes": result["changed_ink_objects"],
                      "missing_text": [x["text"] for p in result["pages"] for x in p["missing_text"]],
                      "added_text": [x["text"] for p in result["pages"] for x in p["added_text"]],
                      "json": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
