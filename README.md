# Artwork Diff

**Vector-aware PDF comparison for approved vs. production packaging artwork.**

Artwork Diff is an experimental, offline-first Python tool that compares PDF **objects**, not just two raster screenshots. It identifies candidate changes in text characters, vector geometry, stroke/fill attributes, embedded images, and page sizes. Results are available as a standalone, clickable HTML report and machine-readable JSON.

> **Safety notice:** This is a review aid, not certified prepress or print-production sign-off software. A report with zero findings does **not** establish that two PDFs will print identically.

## Quick start

Python 3.11+ on Linux, macOS, or Windows:

```sh
git clone https://github.com/tsuuanmi/artwork-diff.git
cd artwork-diff
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e .
artwork-diff approved.pdf production.pdf --out report
```

Alternatively, without installing the console command:

```sh
python compare.py approved.pdf production.pdf --out report
```

Open `report/report.html` in a browser or consume `report/diff.json` in another tool.

The CLI exits with **0** when no differences are found in the supported checks and **1** when it detects one or more differences. These codes do **not** certify print safety.

### Generate safe demo PDFs

Synthetic samples can be generated locally; no customer designs are included:

```sh
python -m pip install -e '.[dev]'
python scripts/create_demo.py
artwork-diff demo/approved.pdf demo/production.pdf --out demo/output
python -m unittest discover -s tests -v
```

The demo intentionally changes a letter, a line width, a fill color, a Bezier path, and adds a small shape.

## Inputs

- **Approved:** the customer's signed-off PDF.
- **Production:** PDF exported from Illustrator or another artwork tool with vector content preserved.
- Artboards, intended output layers, and page geometry should correspond between the two PDFs.
- Native Adobe Illustrator `.ai` is **not** parsed directly; export to PDF first.
- PDFs that contain only flattened images are outside the reliable vector-object comparison scope.

## Checks currently implemented

| Content | What the MVP compares |
| --- | --- |
| Text | Characters, approximate locations, font name/size, fill color, text transform |
| Vector shapes | Lines, rectangles, Bezier path commands/control points, stroke/fill, line width |
| Embedded images | Decoded stream SHA-256, intrinsic size, bounding box |
| Document | Page count, dimensions, added/removed/modified objects |
| Review | HTML side-by-side previews, finding markers, JSON results |

The rendered previews are for **display only**: the detection engine works on extracted PDF objects, not pixel subtraction.

### Options

```text
artwork-diff --help
artwork-diff approved.pdf production.pdf \
  --out report \
  --tolerance-mm 0.05 \
  --match-radius-pt 10
```

The tolerances are experimental heuristic defaults, **not** validated press tolerances.

## Project layout

```text
src/artwork_diff/core.py       PDF object extraction and comparison
src/artwork_diff/reporting.py  Side-by-side HTML review report
src/artwork_diff/cli.py        CLI and JSON output
tests/test_compare.py          Synthetic smoke and regression tests
scripts/create_demo.py        Generates synthetic demonstration PDFs
docs/OPEN_SOURCE_AUDIT.md     Reuse options and license considerations
```

## Known limitations

These capabilities are **not yet fully supported**, so manual prepress checks remain mandatory:

- Illustrator text converted to outlines, font substitutions, reflow, and equivalent vector representations stored differently.
- Complex clipping paths, masks, visibility, hidden layers, transparency, soft masks, blend modes, and overprinting.
- CMYK/ICC, Pantone/spot inks, separation plates, trapping, dielines, varnish/white channels, and other print-specific semantics.
- Automatic alignment across different cropping/artboards; occluded/hidden objects.
- Semantically equal raster images with different encodings; scanned artwork.
- Performance at scale and robustness against malformed/untrusted PDFs.

Even if a shape does not appear visibly different, a changed object may trigger a finding. Conversely, changed appearance can go undetected when it depends on unsupported PDF graphics state.

## Evidence and regression

A **private** pair of customer artwork PDFs uncovered a 28-character text line present in one file and absent in the other. The initial comparator generated 656 findings, mostly from text-matrix rounding noise; the updated grouping and tolerance approach produced one actionable missing-text finding on this specific pair. Those customer PDFs are deliberately **not** part of this public repository.

Synthetic regression tests cover identical documents, several subtle text/vector changes, text-matrix jitter, and grouping of missing characters.

## Reuse strategy

Use existing components for parsing, rendering, content-stream access, and image geometry instead of rebuilding PDF infrastructure. See [Open-source audit](docs/OPEN_SOURCE_AUDIT.md). No evaluated off-the-shelf open-source tool was verified to cover all vector, appearance, and prepress requirements end to end.

## Recommended next steps

1. Create a private labeled dataset of approved/production pairs, with both real faults and benign re-exports.
2. Add appearance-level geometric normalization and an independent high-resolution visual safety check.
3. Parse full color spaces/spot separations/overprint, clipping and transparency.
4. Add an explicit human QA sign-off workflow, immutable approved-file hashes, and audit logs.
5. Benchmark precision/recall across difficult real production cases before considering automated job release.

## License

Project source: [MIT](LICENSE). Third-party packages have their own licenses; verify notices and redistribution terms for the versions you deploy.

For security and confidentiality, **never commit customer PDF/AI files** to this public repository.
