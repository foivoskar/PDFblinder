"""Verify the serialized PDF before publishing it."""

from pathlib import Path
from typing import BinaryIO

import pikepdf

from .sanitize import NAME_MAPS, PAGE_KEYS, forbidden_fields


class VerificationError(RuntimeError):
    """The output does not satisfy the structural sanitation policy."""


FORBIDDEN_TYPES = frozenset(
    {
        "/Metadata",
        "/EmbeddedFile",
        "/Filespec",
        "/Action",
        "/Annot",
        "/Sig",
    }
)


def verify_pdf(
    source: Path | BinaryIO,
    *,
    expected_pages: int,
    original_ids: tuple[bytes, ...] = (),
) -> int:
    """Check structure, not the anonymity of visible or binary content."""
    if expected_pages < 1:
        raise VerificationError("Expected page count must be positive.")

    with pikepdf.Pdf.open(source, attempt_recovery=False) as pdf:
        if pdf.is_encrypted:
            raise VerificationError("Output is encrypted.")
        if "/Info" in pdf.trailer:
            raise VerificationError("Document information dictionary remains.")
        if "/Prev" in pdf.trailer:
            raise VerificationError("Incremental revision reference remains.")
        if set(pdf.Root.keys()) != {"/Type", "/Pages"}:
            raise VerificationError("Unexpected document catalog fields.")
        if len(pdf.pages) != expected_pages:
            raise VerificationError("Output page count does not match.")

        identifiers = pdf.trailer.get("/ID")
        if not isinstance(identifiers, pikepdf.Array):
            raise VerificationError("Output has no document identifiers.")
        if len(identifiers) != 2:
            raise VerificationError("Invalid document identifiers.")
        for identifier in identifiers:
            if not isinstance(identifier, pikepdf.String):
                raise VerificationError("Invalid document identifier type.")
            if bytes(identifier) in original_ids:
                raise VerificationError("Original document identifier remains.")

        for number, page in enumerate(pdf.pages, start=1):
            unexpected = set(page.obj.keys()) - PAGE_KEYS
            if unexpected:
                raise VerificationError(
                    f"Unexpected fields on page {number}: {', '.join(sorted(unexpected))}"
                )

        pending = [(pdf.Root, False), (pdf.trailer, False)]
        visited = set()

        while pending:
            obj, name_map = pending.pop()
            if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
                continue

            if obj.is_indirect:
                identity = (obj.objgen, name_map)
                if identity in visited:
                    continue
                visited.add(identity)

            if isinstance(obj, pikepdf.Array):
                pending.extend((item, False) for item in obj)
                continue

            forbidden = forbidden_fields(obj, name_map)
            if forbidden:
                raise VerificationError("Forbidden fields remain: " + ", ".join(sorted(forbidden)))
            if not name_map and str(obj.get("/Type", "")) in FORBIDDEN_TYPES:
                raise VerificationError("Forbidden object type remains.")

            pending.extend((value, not name_map and key in NAME_MAPS) for key, value in obj.items())

        issues = pdf.check_pdf_syntax()
        issues.extend(pdf.get_warnings())
        if issues:
            raise VerificationError("PDF structural checks failed:\n" + "\n".join(issues))

        return len(pdf.pages)
