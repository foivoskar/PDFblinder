# Security policy

PDFblinder 0.1.0 is a prototype structural sanitizer. It can retain invisible text
and contains a context-insensitive resource-deletion defect. Do not rely on it as
an unattended official journal blinding service. The 0.2 development series adds
mitigations and tests; it has not been independently security-certified.

Treat all submitted PDFs as untrusted. Native parsing occurs in a supervised
worker, but process separation and Ghostscript SAFER are not an OS sandbox. Use
an isolated unprivileged, network-disabled environment for a submission service.
See docs/DEPLOYMENT.md and docs/EDITORIAL_ACCEPTANCE.md.

Do not post confidential PDFs, identifying audit reports or sensitive exploit
samples in public issues. Use GitHub private vulnerability reporting if enabled,
or arrange a private channel with the maintainer before transferring a sample.
Only share documents you have authority to disclose. There is no promised response
SLA; a journal must appoint its own security/operations contact.

Keep Python packages, Ghostscript, the OS and the deployment image patched.
Automated dependency checks are advisory, not proof of safety. Test updates on the
journal corpus and maintain a rollback path. File deletion does not provide
forensic erasure, particularly on SSDs, swap, backups or cloud-synced directories.
