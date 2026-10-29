# Third-party licensing inventory

PDFblinder's original code/documentation is MIT. This does not relicense dependencies
or grant rights to submitted manuscripts or embedded fonts/images.

| Component | Upstream license information |
| --- | --- |
| Ghostscript (separately installed executable) | GNU AGPL or Artifex commercial license: https://www.ghostscript.com/licensing/ |
| pikepdf | MPL-2.0; includes/uses qpdf and other third-party components: https://github.com/pikepdf/pikepdf |
| pypdf | BSD-3-Clause: https://github.com/py-pdf/pypdf |
| pypdfium2 / PDFium binaries | Apache-2.0/BSD-3-Clause plus bundled dependency notices: https://github.com/pypdfium2-team/pypdfium2 |
| Pillow | MIT-CMU and bundled component notices: https://github.com/python-pillow/Pillow |
| psutil | BSD-3-Clause: https://github.com/giampaolo/psutil |

The installed distributions and their bundled notices are authoritative for the
exact versions used. Inspect those and any transitive dependencies, including
qpdf, lxml and binary libraries, when preparing a deployment/license inventory.
A Docker image bundles system packages including Ghostscript; distributing an
image therefore requires a separate review of notices, source availability and
other applicable obligations. Internal CLI use and hosted services are different
deployment cases. The journal must review its actual arrangement, including the
AGPL/commercial Ghostscript choice; this table is not blanket clearance.

The private audit records runtime package and Ghostscript/PDFium versions to
support the journal's inventory and reproducibility process.
