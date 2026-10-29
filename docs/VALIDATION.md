# Validation evidence and limits

The version-controlled tests are the reproducible synthetic regression corpus.
They do not constitute a benchmark of all PDF features or an independent security
audit. The CI matrix runs on Linux, macOS and Windows, Python 3.11/3.14. Cite the
specific commit/run when recording results; do not reuse previous release claims.

## Independent checks

- Ghostscript reconstructs vector output; pikepdf/qpdf performs sanitation and
  structural checks.
- pypdf reparses the serialized candidate with a separately maintained policy,
  including canonical image-only output rules and recognized JPEG metadata checks.
- PDFium renders original/candidate at 144 dpi for vector output, or at the
  selected raster DPI for image-only output, and compares per-page mean error
  (maximum channel mean 1/255) and 32x32 tile mean error (maximum 12/255).
- Vector normalized extracted text must match (NFKC, whitespace ignored).
- Arbitrary alternate text in property dictionaries/content operands is rejected;
  a fixed fi/fl/ff/ffi/ffl/st vocabulary is allowed only with final text equality.
  Some browser ligature/font mappings cannot round-trip through Ghostscript and
  correctly cause rejection. No unvalidated font mapping repair is attempted.
- Vector visibility screening rejects nonstandard text rendering modes, transparent
  text, text outside the crop/media intersection, near-degenerate text, uniformly
  low-contrast text regions, and substantial later object overlap.

Visibility screening is conservative and incomplete. Certain combinations of
clipping, patterned backgrounds, partial covering or custom font/image programs
can evade it. Render comparison can miss changes below its resolution/tolerances;
text extraction is not reliable for every encoding. A custom Type 3 glyph can
have the same extracted character but different drawing commands. Human comparison
and residual-risk acceptance remain mandatory. Multiple parsers reduce common
blind spots; they do not establish formal independence or absence of all bugs.

## Required journal corpus

Synthetic fixtures are committed. A journal should maintain its own restricted,
legally shareable validation corpus with expected results, anonymized before any
public contribution. Include Word, LaTeX and browser exports; Unicode and RTL/CJK
scripts; equations; Type 1/TrueType/Type 3 fonts; raster/vector plots; color spaces;
scans/OCR; rotated/cropped pages; layers; annotations; and malformed/oversized input.
Current synthetic tests do not claim complete coverage of every item on that list.

## Release gate

Run tests/lint, build both sdist and wheel, inspect distribution contents/licenses,
install the wheel in a clean environment and run the tests against that installation.
Review dependency vulnerability reports and OS packages, independent code review,
journal corpus results and the editorial acceptance checklist before promoting a
release. Never publish private manuscripts, audits or input/output hashes in CI.
