# Changelog

## 0.2.0 (2026-10-29)

- Keep text/vector output as default; reject known hidden-text mechanisms.
- Add an explicit lossless image-only profile with no source text/font objects.
- Preserve resource and Type 3 glyph names that resemble action/metadata keys.
- Independently validate output with pypdf and PDFium, including local rendering,
  text and geometry checks; disable Ghostscript automatic page rotation.
- Supervise the entire processing job with time, memory, disk and complexity
  limits; add inherited Linux resource limits and no-clobber publication.
- Add private, versioned audit reports with hashes and human approval pending.
- Expand privacy, fidelity, limit and failure regression fixtures.
- Document threat model, residual risks, isolated deployment, licensing inventory
  and journal-specific acceptance/revalidation requirements.

## 0.1.0

Initial structural sanitation prototype. Not suitable as an unattended official
blinding service; see SECURITY.md for known limitations.
