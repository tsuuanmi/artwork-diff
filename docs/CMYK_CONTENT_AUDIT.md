# Object-level CMYK and content audit

This experimental analysis is an additive tool that groups identical geometric
objects by their **actively painted** CMYK/RGB/Gray colors and detects text that
was added or removed at matching page coordinates.

## Use

After installing this repository in editable mode:

```bash
python -m artwork_diff.ink_audit approved.pdf production.pdf --out ink-audit.json
```

The existing `artwork-diff` CLI still produces its detailed HTML report.
The new auditor produces a grouped JSON summary so one widespread palette change
doesn't become hundreds of unprioritized findings.

## Results confirmed with three private packaging-artwork PDFs

- The original and red variants had equal extracted geometry and text.
- An ink replacement from `DeviceCMYK 100/90/0/10` to
  `DeviceCMYK 0/100/100/0` affected **528 active painted objects**:
  208 text characters, 238 vector paths, and 82 filled rectangles.
- Seven other rectangles contained a stored changed fill-color state but did not
  fill, so they were excluded from the meaningful-color count.
- A third version retained the red color but removed the two-character label
  `C1`. Its shape geometry matched the red version.
- The third version also had one fewer PDF clipping operator. That fact alone
  does not demonstrate a new independent clipping defect.
- These particular page resources declared no named spot/Separation/DeviceN
  colors. DeviceCMYK operators were present, with overprint disabled in the
  declared ExtGState.

The private source files are **not** checked into Git.

## Technical scope

- Geometry: quantizes PDF object coordinates and path commands to 0.02 pt.
  This is tolerance-based path matching, **not** full Bezier-equivalence
  canonicalization.
- Ink: compares fill only when an object is filled; stroke only when stroked.
  Text rendering mode is not yet fully modeled.
- Text: compares characters at document coordinates and groups neighboring
  added/missing characters into readable runs.
- Preflight: identifies page-level spot-resource declarations, overprint fields,
  and clipping operator counts. It does **not** recursively analyze Form
  XObjects, simulate spot tints or separation plates, or evaluate the clipping
  regions and blending.
- Embedded images are not evaluated by this audit; the base comparator provides
  a separate image comparison path.

**Do not release a production print job solely because this tool reports
zero differences.** Follow normal prepress checks and human sign-off.
