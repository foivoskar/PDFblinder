# Editorial acceptance and threat model

Status: proposed operational policy, not certification or a claim that a journal
has approved PDFblinder. A named journal owner must accept this policy and its
residual risks before using any version as an official tool.

## Intended protection

Protect against accidental disclosure through common PDF metadata, auxiliary
objects, source IDs and known hidden-text mechanisms. Preserve scientific page
content under the tested rendering/text checks. Process potentially hostile
input only within the deployment isolation described separately.

A reviewer may inspect metadata, extract text, inspect objects and compare files.
We do not claim protection against deliberate steganography, distinctive author
writing/figure styles, preprints, recognizable datasets, arbitrary payloads in
font/image programs, or identities visible in the manuscript. Input/output hashes
are intentionally held in a private audit, not shared with reviewers.

## Profile selection

Use vector by default for normal manuscripts, retaining text and vector graphics.
A rejection is a request for investigation, not permission to bypass checks.
Re-export from the author's source document where practical. Raster may be used
only under the journal's documented policy, after reviewing the loss of search,
copy/paste, accessibility and resolution-independent detail. Never silently
rasterize a failed document. Do not automatically remove human names by guessing.

Comments/highlights are discarded, including legitimate scientific feedback.
Decide whether the workflow requires those annotations before using this tool.
Keep the original and source document in restricted editorial storage.

## Before adopting a release

- Name an editorial owner and a technical/security maintainer.
- Record the exact package version, source commit, dependency versions and OS.
- Validate a legally shareable corpus representative of this journal: authoring
  systems, languages, mathematics, maps, plots, fonts, scanned pages and supplements.
- Include deliberately identifying metadata and hidden-text fixtures with known
  expected outcomes, and compare against an independent inspection process.
- Review original/output renderings for all pages at normal and high zoom; inspect
  equations, subscripts, small symbols, map legends, scale bars and color keys.
- Decide acceptable rejection rates and the escalation/re-export procedure.
- Validate isolation, limits, job cancellation, crash recovery, storage permissions,
  retention/deletion, backups, network restrictions and operational logging.
- Review licensing for the journal's actual deployment, including Ghostscript.
- Record a signed acceptance decision and review date. The automated test count
  alone is not acceptance evidence. No acceptance decision is supplied by this repo.

## For each manuscript or review report

1. Confirm that the input belongs to the intended submission and policy profile.
2. Run PDFblinder in the approved environment; preserve the private audit.
3. On any rejection, quarantine the job and investigate/re-export. Never send a
   partially processed file or treat a failed job as a successful blinding.
4. A human checks every output page and all reviewer-visible supplementary files,
   filenames, links, names, affiliations, acknowledgements and identifying text.
5. A human compares scientific content, equations, figures, page order and cropping
   with the original. Raster requires explicit review of image resolution.
6. Record reviewer/operator identity, UTC date, input/output hashes, approval or
   rejection and reasons in the journal's access-controlled editorial system.
7. Send only the approved PDF with a neutral filename. Do not send the audit or
   original, and do not mistake `technical_status: passed` for editorial approval.

## Change control

Revalidate after changes to the tool, Ghostscript, PDFium, qpdf/pikepdf, pypdf,
fonts, OS/container or acceptance policy. Keep a tested environment snapshot and
rollback procedure. Retain only the records required by the journal's policy.
