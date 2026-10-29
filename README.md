# PDFblinder

[![PyPI](https://img.shields.io/pypi/v/pdfblinder)](https://pypi.org/project/pdfblinder/)
[![Tests](https://github.com/foivoskar/PDFblinder/actions/workflows/tests.yml/badge.svg)](https://github.com/foivoskar/PDFblinder/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

PDF reconstruction and sanitation for scientific review workflows, with
independent structural/rendering checks and a private audit report.

**Version 0.2.0 adds the safeguards described below.
Technical success is never a certificate of anonymity or editorial
approval.** Journals must adopt a policy and validate representative documents
before deployment. See [editorial acceptance](docs/EDITORIAL_ACCEPTANCE.md).

## Installation

Python 3.11+ and a separately installed [Ghostscript](https://ghostscript.com/releases/)
are required. The existing published release can be installed with:

```sh
python -m pip install pdfblinder
```

To install from a source checkout, use an isolated environment:

```sh
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

The CLI finds `gs`, `gswin64c`, or `gswin32c` on PATH. Select a different
executable with `--gs "/path/to/gs"`. Ghostscript is not installed by pip.

## Default: preserve text and vector graphics

```sh
pdfblinder "input.pdf" "review.pdf"
```

The `vector` profile reconstructs with Ghostscript/pdfwrite and sanitizes with
pikepdf. It preserves text/vector content when checks pass. Known invisible,
transparent, off-page, very small, low-contrast and potentially covered text
causes rejection. Arbitrary alternate text is rejected; a fixed set of standard
ligatures is permitted only with final normalized text equality. Forms/signatures, optional-content layers and nonstandard
UserUnit pages require re-export or manual investigation. These checks are
conservative and can reject legitimate documents, including scanned PDFs with
invisible OCR. **They do not detect every possible concealed payload.**

The serialized candidate is checked with qpdf/pikepdf and a separately specified
pypdf policy. PDFium independently compares page geometry, normalized extracted
text and page renderings at 144 dpi for vector output (the chosen raster DPI
for image-only output), including local 32-pixel tiles. A renderer
mismatch rejects the job. Finite-resolution comparison is not proof of visual
identity at every zoom, nor proof that every scientific detail is preserved.
Some browser ligature/font combinations change extracted text during pdfwrite;
these are rejected and require re-export or explicit raster processing. The tool
does not guess or automatically repair arbitrary font mappings.

## Optional image-only profile

```sh
pdfblinder --profile raster --dpi 300 "input.pdf" "review.pdf"
```

This renders the visible page with PDFium and builds a fresh PDF from lossless
RGB pixels. No source fonts, text objects, OCR layers or image containers are
copied. A second parser enforces canonical image-only page commands/resources.
It **loses selectable/searchable text, vector scalability and accessibility**;
review small symbols and figures at the intended viewing/printing resolution.
Visible identifiers and information encoded in pixels still remain. Raster is
an explicit alternative, never an automatic fallback for a rejected vector job.

## Output and private audit

Both output paths must be new, and their directories must exist:

```sh
pdfblinder --report "/private/editorial/job.json" "input.pdf" "review.pdf"
```

Without `--report`, the audit is `review.pdf.audit.json`. It records input/output
SHA-256 hashes, a run ID, UTC time, tool/dependency versions, profile, discarded
annotation count, limits and comparison results. It contains no input filename
or copied metadata values. **Hashes still link the output to the original:
keep the audit in restricted editorial storage and do not send it to reviewers.**

Every report has `human_review: pending` and `approved_for_submission: false`.
Record human approval separately in the journal's editorial system, bound to
the output hash. There is no automatic approval switch.

Output and audit are published after technical checks, with restrictive file
permissions and no-clobber hard links. Filesystems must support hard links;
unsupported filesystems fail rather than fall back to overwriting. Publication
of the two files is not a single transaction: abrupt termination can leave an
audit without a PDF or hidden staging files. Existing files are not overwritten.

## Limits and deployment

The entire parse/render/check job runs in a separate supervised process tree.
`--timeout` applies to the whole processing job (default 120 seconds). Defaults:
100 MiB input, 512 MiB temporary working data, 1536 MiB sampled process-tree RSS,
200 pages, 100,000 PDF objects, 20,000 drawing objects per page, 32 form nesting
levels, 25 million pixels per rendered page and 250 million pixels per pass.

```sh
pdfblinder --timeout 300 --max-input-mb 100 --max-work-mb 512 \
  --max-memory-mb 1536 --max-pages 200 "input.pdf" "review.pdf"
```

Memory/disk usage is sampled; short peaks can exceed the configured values.
Linux also applies inherited address-space, CPU, file-size and core-dump limits.
If resource monitoring is unavailable the job stops. A worker process and
Ghostscript SAFER **are not an OS security sandbox**. For documents from untrusted
submitters, use OS isolation with no network and hard resource/filesystem limits.
See [deployment guidance](docs/DEPLOYMENT.md) and [security policy](SECURITY.md).

## What this does not do

- Remove names, affiliations, acknowledgements, identifying citations, visible
  watermarks, identifying figures, filenames, or revealing URLs from page content.
- Establish anonymity against steganography, font/image fingerprinting or an
  attacker who deliberately encodes identity into legitimate-looking content.
- Exhaustively rewrite metadata internal to every font/image format in vector
  mode. JPEG auxiliary application/comment segments (including EXIF, XMP,
  Photoshop/IPTC and thumbnails) remaining in output cause rejection. Only
  minimal JFIF and Adobe color-transform headers are allowed.
- Preserve annotations (including highlights), links, bookmarks, structure tags,
  forms, signatures or original accessibility information.
- Guarantee forensic erasure from storage, swap, backups or cloud synchronization.

The application processes locally and needs no network during a job. Renderer
error details are withheld from normal output to avoid exposing manuscript text.

## Development and validation

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check src tests
```

Synthetic regression fixtures cover hidden/transparent/covered/off-page text,
Type 3/resource-name preservation, embedded Unicode fonts, images/transparency,
rotated/cropped pages, independent tampering checks, resource limits, audit
privacy and publication failures. Private manuscripts are never test fixtures.
GitHub Actions tests Linux/macOS/Windows with Python 3.11 and 3.14. Its current
run is the evidence for a particular commit; previous 0.1 results do not certify
this release. See [validation scope](docs/VALIDATION.md).

Exit codes: 0 for technical success requiring human review, 1 for processing
failure/rejection, 2 for argument errors, 130 for interruption. A failed job
publishes neither output nor audit during handled failures.

## License

Original code and documentation: [MIT](LICENSE), copyright (c) 2026 foivoskar.
Dependencies keep their own licenses. Ghostscript is installed separately and
is available under GNU AGPL or an Artifex commercial license. MIT does not waive
third-party obligations, including redistribution or hosted-service conditions.
See [third-party licensing](docs/THIRD_PARTY.md).
