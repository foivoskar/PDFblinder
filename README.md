# PDFblinder

[![PyPI](https://img.shields.io/pypi/v/pdfblinder)](https://pypi.org/project/pdfblinder/)
[![Tests](https://github.com/foivoskar/PDFblinder/actions/workflows/tests.yml/badge.svg)](https://github.com/foivoskar/PDFblinder/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Python command-line tool that reconstructs PDFs with Ghostscript,
removes selected structural metadata and auxiliary objects with pikepdf,
and verifies the serialized result before creating the destination file.

Designed for preparing documents for double-blind review.

**Structural sanitation does not guarantee complete anonymity.**
Identifying visible content remains. Always inspect the output.

## Requirements

- Python 3.11 or newer.
- Ghostscript installed separately.
- Ghostscript available as `gs`, `gswin64c`, or `gswin32c`,
  or supplied explicitly with `--gs`.

The test suite has passed on GitHub Actions on Linux, macOS, and Windows
with Python 3.11 and 3.14.

## Installation

Install from [PyPI](https://pypi.org/project/pdfblinder/), preferably in
a virtual environment:

```sh
python -m pip install pdfblinder
```

Verify the installation:

```sh
pdfblinder --version
```

Ghostscript is not installed by pip. Install it separately using your
system's package manager or the
[official Ghostscript downloads](https://ghostscript.com/releases/).

## Usage

```sh
pdfblinder input.pdf output.pdf
```

Quote paths containing spaces:

```sh
pdfblinder "original manuscript.pdf" "review copy.pdf"
```

Select a Ghostscript executable or change its timeout:

```sh
pdfblinder --gs "/path/to/gs" --timeout 300 input.pdf output.pdf
```

The module entry point is also available:

```sh
python -m pdfblinder input.pdf output.pdf
```

The destination must not already exist. The original file is preserved.
The output directory must already exist.

Exit codes: `0` for success, `1` for processing failure,
`2` for invalid command-line arguments, and `130` for interruption.

## Processing and verification

1. Copy the input into a private temporary working directory.
2. Reject encrypted PDFs, empty documents, and documents with AcroForm
   forms or signature fields.
3. Reconstruct pages using Ghostscript's `pdfwrite` device.
   Annotations are discarded rather than painted onto the pages.
4. Create a new PDF from the reconstructed pages. Restrict page fields,
   strip selected auxiliary dictionary fields, and remove unused resources.
5. Reopen the serialized candidate. Check the page count, document catalog,
   absence of document information metadata, forbidden fields and object
   types, document identifiers, and PDF syntax.
6. Create the destination exclusively and copy the verified bytes into it.

Temporary working files are cleaned up on normal completion and handled
exceptions. Abrupt process termination or power loss may leave temporary
files or an incomplete destination.

## Scope and limitations

- Names, affiliations, acknowledgements, citations, watermarks, and other
  identifying visible content remain.
- Embedded font and image payloads are not exhaustively inspected or
  anonymized. Reconstruction can retain distinctive document features.
- The structural checks enforce a defined policy; they cannot prove that
  every possible identifying byte or covert channel has been eliminated.
- Comments, highlights, links, and other annotations are discarded.
  Bookmarks, document tags, and accessibility structure are not preserved.
- Forms and signature fields are rejected to avoid silently losing their
  appearance or misrepresenting signatures.
- Page count and syntax checks do not establish full visual equivalence.
  Inspect every output before submission.
- Output identifiers are newly generated; original identifiers are checked
  for reuse. Filesystem timestamps and permissions are newly created.
  The output filename is chosen by the user.
- Keep Ghostscript and pikepdf updated. Ghostscript's SAFER mode is enabled,
  but it is not a complete operating-system sandbox.
- The timeout applies to Ghostscript reconstruction, not the entire job.

## Development

From a checkout of this repository, create a virtual environment:

```sh
python -m venv .venv
```

Activate it on macOS or Linux:

```sh
source .venv/bin/activate
```

Or in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the development dependencies and run the tests:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
```

Tests cover reconstruction, sanitation, verification, CLI behavior,
overwrite protection, failure handling, text preservation, and a rendered
comparison of a synthetic page containing text and vector graphics.

Test PDFs are generated in temporary directories. No private documents
are needed in the repository.

## License

PDFblinder's original code and documentation are licensed under the
[MIT License](LICENSE), copyright (c) 2026 foivoskar.

Third-party dependencies retain their own licenses. Ghostscript is installed
separately and is not bundled with PDFblinder. It is available under the
GNU AGPL or a commercial license from Artifex.

The MIT license for PDFblinder does not waive any third-party obligations.
Before redistributing Ghostscript or deploying a hosted PDF-processing
service, evaluate the applicable
[Ghostscript licensing terms](https://www.ghostscript.com/licensing/).
