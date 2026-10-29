"""Structural sanitation of Ghostscript's intermediate PDF."""

from pathlib import Path
from typing import BinaryIO

import pikepdf


PAGE_KEYS = frozenset({
    "/Type", "/Parent", "/MediaBox", "/CropBox",
    "/BleedBox", "/TrimBox", "/ArtBox", "/Rotate",
    "/UserUnit", "/Resources", "/Contents", "/Group",
})

FORBIDDEN_KEYS = frozenset({
    "/Metadata", "/PieceInfo", "/LastModified",
    "/Annots", "/AA", "/A", "/OpenAction",
    "/AcroForm", "/XFA", "/JavaScript", "/JS",
    "/EmbeddedFiles", "/EF", "/AF", "/Collection",
    "/RichMediaContent", "/RichMediaSettings",
    "/StructTreeRoot", "/StructParents", "/StructParent",
    "/SpiderInfo", "/PresSteps",
})


class SanitationError(RuntimeError):
    """The intermediate PDF cannot be sanitized."""


def _strip_auxiliary_data(pdf: pikepdf.Pdf) -> None:
    pending = [pdf.Root]
    visited = set()

    while pending:
        obj = pending.pop()
        if not isinstance(
            obj, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)
        ):
            continue

        if obj.is_indirect:
            identity = obj.objgen
            if identity in visited:
                continue
            visited.add(identity)

        if isinstance(obj, pikepdf.Array):
            pending.extend(obj)
            continue

        for key in list(obj.keys()):
            if key in FORBIDDEN_KEYS:
                del obj[key]
            else:
                pending.append(obj[key])


def sanitize_intermediate(
    source: Path,
    destination: BinaryIO,
) -> int:
    """Write a sanitized PDF to a caller-managed binary stream.

    Call only after Ghostscript reconstruction. Verification and
    publication of the result are separate stages.
    Visible content and embedded font/image payloads are not anonymized.
    """
    with pikepdf.Pdf.open(
        source, attempt_recovery=False
    ) as original, pikepdf.Pdf.new() as clean:
        if original.is_encrypted:
            raise SanitationError("Encrypted intermediate PDF rejected.")
        if len(original.pages) == 0:
            raise SanitationError("PDF contains no pages.")

        clean.pages.extend(original.pages)

        for page in clean.pages:
            for key in list(page.obj.keys()):
                if key not in PAGE_KEYS:
                    del page.obj[key]

        _strip_auxiliary_data(clean)
        clean.remove_unreferenced_resources()
        clean.save(
            destination,
            min_version="1.7",
            fix_metadata_version=False,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        return len(clean.pages)
