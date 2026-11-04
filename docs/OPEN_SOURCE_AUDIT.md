# Open-source reuse audit

Reviewed: 2026-11-04. Target: reliable pre-production comparison of customer-approved PDFs against production PDFs exported from Adobe Illustrator, with object-level changes, geometry, text, and print-specific constraints.

**Conclusion:** Reuse PDF extraction/rendering/graphics infrastructure. No evaluated single open-source product was verified to offer reliable, complete object-level **and** prepress comparison with commercial-production sign-off. This is a scoped assessment, not proof that none exists.

## Comparison

| Project | Role | License (check distributed version) | Fit / decision |
| --- | --- | --- | --- |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | Extract characters, lines, rectangles, curves, path controls, images | MIT | **Adopted.** Useful object-level extraction; does not reconstruct full PDF graphics state. |
| [pypdfium2 / PDFium](https://github.com/pypdfium2-team/pypdfium2) | Render preview pages; PDFium page-object APIs | Apache-2.0 / BSD-3-Clause for bindings; PDFium BSD-style + dependencies | **Adopted for previews.** Evaluate raw page-object API for future graphics-state-aware checks. Raw PDF dictionaries/streams are not exposed by PDFium's public interface. |
| [pikepdf / QPDF](https://github.com/pikepdf/pikepdf) | Parse PDF dictionaries, content streams, resource relationships, spot color metadata | MPL-2.0; bundled libraries have separate terms | **Recommended next dependency**, especially for PDF internals not available from PDFium. Not itself an artwork differ. |
| [diff-pdf](https://github.com/vslavik/diff-pdf) | Rendered visual comparison + visual diff output | GPL-2.0-or-later | **Optional independent visual check**, not vector-object comparison. Avoid copying/embedding GPL source into MIT code without an appropriate license plan. |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | Fast PDF parsing/rendering and drawing inspection | AGPL or commercial license | **Evaluate only with legal review** if a proprietary distribution is planned. Not necessary for current MVP. |

License information and package internals should be checked against exact released artifacts, not just repository summaries.

## Why not simply fork diff-pdf?

Its focus is visual PDF comparison. Raster output can reveal some visible differences that an object comparer misses, but cannot directly explain a Bezier control-point change, a font-matrix change, or the original PDF object involved. It also cannot replace prepress analysis of nonvisual metadata such as color separations and overprint semantics.

## Target architecture

1. **Parser:** use pdfplumber for fast extraction; supplement with pikepdf/QPDF for low-level resources and graphics-state operators.
2. **Canonicalization:** normalize fonts, coordinate transforms, path geometry, attributes, and comparable image fingerprints.
3. **Matcher:** stable geometry-aware object correspondence. Preserve both the raw difference and a grouped human-readable finding.
4. **Independent appearance check:** render at several scales and, eventually, per print separation. Object and appearance layers should corroborate or flag discrepancies.
5. **Preflight:** inspect output intent, process and spot inks, overprint, transparency, clipping, trapping, dieline/varnish plates; compare explicitly.
6. **Review:** show a bounding box, object category, reason, page location, severity, approved reference hash, and human disposition.

## Important false-positive and false-negative cases

- Same visible rectangle, different drawing instructions.
- Text converted to outlines on only one side.
- Re-export changes font-subset names or very small transform values.
- Relative page alignment/artboard shift with otherwise identical content.
- Changed CMYK/spot-color semantics with little or no RGB preview difference.
- Invisible or clipped object changes; overprint and transparency interactions.
- Recompressed image whose decoded samples differ slightly.
- Objects behind other objects that never contribute to printed appearance.

## Next validation experiment

Build a private benchmark from known real artwork defects:
- missing or added tiny strokes/text;
- changed phone numbers or regulatory details;
- modified logos and package dielines;
- CMYK/spot/overprint differences;
- benign Illustrator re-export variations.

Record precision, recall, per-page runtime, and failure modes. **Do not** treat a zero-findings result as a release authorization until those cases are covered and independently verified.

## Sources

- pdfplumber project and MIT license: https://github.com/jsvine/pdfplumber
- pypdfium2 bindings, raw API limitations and license: https://github.com/pypdfium2-team/pypdfium2
- pikepdf architecture and MPL-2.0 license: https://github.com/pikepdf/pikepdf
- diff-pdf visual comparison, GPL license: https://github.com/vslavik/diff-pdf
- PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
