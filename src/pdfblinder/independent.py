"""A second parser and separately specified output policy (pypdf)."""

import re
from io import BytesIO

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject, StreamObject

from .inspection import InspectionError
from .limits import LimitError

# Intentionally separate from the sanitizer's tables. Regression tests enforce
# independently specified privacy and preservation requirements.
_NAME_DICTIONARIES = {
    "/Font",
    "/XObject",
    "/ExtGState",
    "/ColorSpace",
    "/Pattern",
    "/Shading",
    "/Properties",
    "/CharProcs",
}
_UNWANTED = {
    "/Metadata",
    "/PieceInfo",
    "/LastModified",
    "/Annots",
    "/AA",
    "/A",
    "/OpenAction",
    "/AcroForm",
    "/XFA",
    "/JS",
    "/JavaScript",
    "/EF",
    "/EmbeddedFiles",
    "/AF",
    "/ActualText",
    "/Alt",
    "/Collection",
    "/StructTreeRoot",
    "/StructParent",
    "/StructParents",
    "/Author",
    "/Creator",
    "/Producer",
    "/CreationDate",
    "/ModDate",
}


def verify_independently(source, limits, *, expected_pages, profile):
    reader = PdfReader(source, strict=True)
    if reader.is_encrypted or "/Info" in reader.trailer or "/Prev" in reader.trailer:
        raise InspectionError("Independent parser found metadata, encryption or revisions.")
    if set(reader.root_object) != {"/Type", "/Pages"}:
        raise InspectionError("Independent catalog check failed.")
    if len(reader.pages) != expected_pages:
        raise InspectionError("Independent page count failed.")
    seen, pending, count = set(), [(reader.trailer, False, 0)], 0
    while pending:
        obj, name_map, depth = pending.pop()
        if isinstance(obj, IndirectObject):
            identity = (obj.idnum, obj.generation, name_map)
            if identity in seen:
                continue
            seen.add(identity)
            obj = obj.get_object()
        count += 1
        if count > limits.max_objects * 20 or depth > limits.max_depth * 4:
            raise LimitError("Independent object traversal limit exceeded.")
        if isinstance(obj, ArrayObject):
            pending.extend((v, False, depth + 1) for v in obj)
        elif isinstance(obj, DictionaryObject):
            if not name_map:
                unwanted = set(obj) & _UNWANTED
                if "/ActualText" in unwanted and str(obj["/ActualText"]) in {
                    "fi",
                    "fl",
                    "ff",
                    "ffi",
                    "ffl",
                    "st",
                }:
                    unwanted.remove("/ActualText")
                if unwanted:
                    raise InspectionError("Independent parser found forbidden auxiliary fields.")
                if str(obj.get("/Type", "")) in {
                    "/Metadata",
                    "/Filespec",
                    "/EmbeddedFile",
                    "/Action",
                    "/Annot",
                    "/Sig",
                }:
                    raise InspectionError("Independent parser found an unsafe object type.")
                if profile == "vector" and obj.get("/Subtype") == "/Image":
                    filters = obj.get("/Filter", [])
                    if isinstance(filters, str):
                        filters = [filters]
                    if "/DCTDecode" in filters and isinstance(obj, StreamObject):
                        # JPEG containers can carry EXIF/comments even without PDF XMP.
                        with Image.open(BytesIO(obj.get_data())) as image:
                            if (
                                image.getexif()
                                or image.info.get("comment")
                                or image.info.get("xmp")
                            ):
                                raise InspectionError(
                                    "JPEG auxiliary metadata remains; use raster or re-export."
                                )
            pending.extend(
                (value, not name_map and key in _NAME_DICTIONARIES, depth + 1)
                for key, value in obj.items()
            )
    # Independently inspect marked-content operands, not just dictionaries.
    drawings = [(page.get_contents(), page.get("/Resources", {})) for page in reader.pages]
    checked = set()
    while drawings:
        drawing, resources = drawings.pop()
        if drawing is None:
            continue
        identity = id(drawing)
        if identity in checked:
            continue
        checked.add(identity)
        if len(checked) > limits.max_objects:
            raise LimitError("Drawing traversal limit exceeded.")
        for operands, operator in ContentStream(drawing, reader).operations:
            if operator not in {b"BDC", b"DP"}:
                continue
            for operand in operands:
                if isinstance(operand, str) and operand.startswith("/"):
                    operand = resources.get("/Properties", {}).get(operand, operand)
                    if isinstance(operand, IndirectObject):
                        operand = operand.get_object()
                if not isinstance(operand, DictionaryObject):
                    continue
                if set(operand) & {"/Alt", "/E", "/OC"}:
                    raise InspectionError("Unapproved alternate/optional content remains.")
                if "/ActualText" in operand and str(operand["/ActualText"]) not in {
                    "fi",
                    "fl",
                    "ff",
                    "ffi",
                    "ffl",
                    "st",
                }:
                    raise InspectionError("Unapproved alternate text remains in a content stream.")
        for item in resources.get("/XObject", {}).values():
            if isinstance(item, IndirectObject):
                item = item.get_object()
            if item.get("/Subtype") == "/Form":
                drawings.append((item, item.get("/Resources", {})))
    if profile == "raster":
        for page in reader.pages:
            if set(page) - {"/Type", "/Parent", "/MediaBox", "/Resources", "/Contents"}:
                raise InspectionError("Unexpected field in raster page.")
            resources = page["/Resources"]
            if set(resources) != {"/XObject"} or set(resources["/XObject"]) != {"/Im0"}:
                raise InspectionError("Raster resources contain more than one canonical image.")
            image = resources["/XObject"]["/Im0"].get_object()
            if set(image) - {
                "/Type",
                "/Subtype",
                "/Width",
                "/Height",
                "/ColorSpace",
                "/BitsPerComponent",
                "/Filter",
                "/Length",
            }:
                raise InspectionError("Unexpected raster image fields.")
            if (
                image.get("/Subtype") != "/Image"
                or image.get("/ColorSpace") != "/DeviceRGB"
                or image.get("/BitsPerComponent") != 8
            ):
                raise InspectionError("Raster image is not canonical RGB.")
            width, height = map(int, (image["/Width"], image["/Height"]))
            if width < 1 or height < 1 or width * height > limits.max_page_pixels:
                raise LimitError("Raster image pixel limit exceeded.")
            if len(image.get_data()) != width * height * 3:
                raise InspectionError("Raster image payload has unexpected bytes.")
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            expected = f"q\n{w:.8f} 0 0 {h:.8f} 0 0 cm\n/Im0 Do\nQ\n".encode()
            commands = page.get_contents().get_data()
            prefix, separator, commands = commands.partition(b"\n")
            if not re.fullmatch(rb"%pdfblinder-instance:[0-9a-f]{32}", prefix):
                raise InspectionError("Invalid raster instance nonce.")
            if commands != expected:
                raise InspectionError("Raster page has noncanonical drawing commands.")
    return {"parser": "pypdf", "status": "passed"}
