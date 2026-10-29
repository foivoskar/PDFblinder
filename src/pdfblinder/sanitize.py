"""Context-aware sanitation. Resource names are not action slots."""

import secrets
from pathlib import Path
from typing import BinaryIO

import pikepdf

PAGE_KEYS = frozenset(
    {
        "/Type",
        "/Parent",
        "/MediaBox",
        "/CropBox",
        "/BleedBox",
        "/TrimBox",
        "/ArtBox",
        "/Rotate",
        "/UserUnit",
        "/Resources",
        "/Contents",
        "/Group",
    }
)
FORBIDDEN_KEYS = frozenset(
    {
        "/Metadata",
        "/PieceInfo",
        "/LastModified",
        "/Annots",
        "/AA",
        "/A",
        "/OpenAction",
        "/AcroForm",
        "/XFA",
        "/JavaScript",
        "/JS",
        "/EmbeddedFiles",
        "/EF",
        "/AF",
        "/Collection",
        "/RichMediaContent",
        "/RichMediaSettings",
        "/StructTreeRoot",
        "/StructParents",
        "/StructParent",
        "/SpiderInfo",
        "/PresSteps",
        "/ActualText",
        "/Alt",
    }
)
NAME_MAPS = frozenset(
    {
        "/Font",
        "/XObject",
        "/ExtGState",
        "/ColorSpace",
        "/Pattern",
        "/Shading",
        "/Properties",
        "/CharProcs",
    }
)


class SanitationError(RuntimeError):
    """The intermediate PDF cannot be sanitized."""


def forbidden_fields(obj, name_map=False):
    fields = set() if name_map else set(obj.keys()) & FORBIDDEN_KEYS
    if "/ActualText" in fields and str(obj["/ActualText"]) in {
        "fi",
        "fl",
        "ff",
        "ffi",
        "ffl",
        "st",
    }:
        fields.remove("/ActualText")
    return fields


def _strip_auxiliary_data(pdf):
    pending = [(pdf.Root, False)]
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
        for key in forbidden_fields(obj, name_map):
            del obj[key]
        pending.extend((value, not name_map and key in NAME_MAPS) for key, value in obj.items())


def sanitize_intermediate(source: Path, destination: BinaryIO) -> int:
    """Preserve page commands and remove auxiliary data by dictionary role."""
    with pikepdf.Pdf.open(source, attempt_recovery=False) as original, pikepdf.Pdf.new() as clean:
        if original.is_encrypted:
            raise SanitationError("Encrypted intermediate PDF rejected.")
        if not original.pages:
            raise SanitationError("PDF contains no pages.")
        clean.pages.extend(original.pages)
        for page in clean.pages:
            for key in set(page.obj.keys()) - PAGE_KEYS:
                del page.obj[key]
        _strip_auxiliary_data(clean)
        clean.remove_unreferenced_resources()
        clean.trailer["/ID"] = pikepdf.Array(
            [
                pikepdf.String(secrets.token_bytes(16)),
                pikepdf.String(secrets.token_bytes(16)),
            ]
        )
        clean.pages[0].contents_coalesce()
        contents = clean.pages[0].obj["/Contents"]
        contents.write(
            f"%pdfblinder-instance:{secrets.token_hex(16)}\n".encode() + contents.read_bytes()
        )
        clean.save(
            destination,
            deterministic_id=True,
            min_version="1.7",
            fix_metadata_version=False,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        return len(clean.pages)
