"""Independent PDFium inspection and per-page rendering comparison.

Visibility checks are conservative detectors, not a proof of anonymity.
"""

import ctypes
import math
import unicodedata
from contextlib import closing

import pypdfium2 as pdfium
from PIL import ImageChops, ImageStat
from pypdfium2 import raw

from .limits import LimitError


class InspectionError(RuntimeError):
    """The document requires manual investigation or changed appearance."""


def normalized_text(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def checked_image(page, dpi, limits):
    w, h = page.get_size()
    width, height = math.ceil(w * dpi / 72), math.ceil(h * dpi / 72)
    if not all(math.isfinite(n) and n > 0 for n in (w, h)):
        raise InspectionError("Invalid page dimensions.")
    if width * height > limits.max_page_pixels:
        raise LimitError("Page exceeds the rendered pixel limit.")
    bitmap = page.render(scale=dpi / 72, may_draw_forms=False, draw_annots=False)
    try:
        return bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()


def _bounds(obj):
    bounds = obj.get_bounds()
    parent = obj.container
    while parent is not None:
        bounds = parent.get_matrix().on_rect(*bounds)
        parent = parent.container
    return bounds


def _pixel_box(page, bounds, size):
    points = []
    for x, y in [(bounds[0], bounds[1]), (bounds[2], bounds[3])]:
        px, py = ctypes.c_int(), ctypes.c_int()
        if not raw.FPDF_PageToDevice(
            page, 0, 0, *size, 0, x, y, ctypes.byref(px), ctypes.byref(py)
        ):
            raise InspectionError("Cannot map text geometry to the page.")
        points.append((px.value, py.value))
    return (
        max(0, min(p[0] for p in points)),
        max(0, min(p[1] for p in points)),
        min(size[0], max(p[0] for p in points) + 1),
        min(size[1], max(p[1] for p in points) + 1),
    )


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def inspect_visibility(page, image, limits, number):
    """Reject known hidden-text mechanisms and ambiguous occlusion.

    Does not classify all conceivable clipping/overpainting combinations.
    """
    bbox = page.get_bbox()
    text_boxes = []
    with closing(page.get_textpage()) as textpage:
        count = 0
        for obj in page.get_objects(max_depth=limits.max_depth, textpage=textpage):
            count += 1
            if count > limits.max_page_objects:
                raise LimitError("Too many page drawing objects.")
            if obj.type == raw.FPDF_PAGEOBJ_FORM:
                if obj.level >= limits.max_depth - 1:
                    raise LimitError("Form nesting exceeds inspection depth.")
                continue
            bounds = _bounds(obj)
            if not all(math.isfinite(n) for n in bounds):
                raise InspectionError(f"Invalid object geometry on page {number}.")
            if obj.type != raw.FPDF_PAGEOBJ_TEXT:
                if obj.type in (
                    raw.FPDF_PAGEOBJ_IMAGE,
                    raw.FPDF_PAGEOBJ_PATH,
                    raw.FPDF_PAGEOBJ_SHADING,
                ):
                    for previous in text_boxes:
                        area = (previous[2] - previous[0]) * (previous[3] - previous[1])
                        if area > 0 and _intersection(previous, bounds) / area > 0.5:
                            raise InspectionError(
                                f"Potentially covered text on page {number}; manual investigation required."
                            )
                continue
            text = obj.extract()
            # Empty/unmapped glyphs still have a visual role; inspect them too.
            if text and not text.strip():
                continue
            mode = raw.FPDFTextObj_GetTextRenderMode(obj)
            if mode not in (0, 1, 2):
                raise InspectionError(f"Invisible or clipping text on page {number}.")
            # Chromium emits empty, zero-area text objects between words.
            # They carry neither extractable characters nor rendered glyphs.
            if not text and abs(bounds[2] - bounds[0]) < 1e-6 and abs(bounds[3] - bounds[1]) < 1e-6:
                continue
            colors = [ctypes.c_uint() for _ in range(4)]
            get_color = (
                raw.FPDFPageObj_GetStrokeColor if mode == 1 else raw.FPDFPageObj_GetFillColor
            )
            if not get_color(obj, *(ctypes.byref(c) for c in colors)):
                raise InspectionError(f"Cannot inspect text opacity on page {number}.")
            if colors[3].value < 250:
                raise InspectionError(f"Transparent text on page {number}.")
            if (
                bounds[0] < bbox[0] - 0.5
                or bounds[1] < bbox[1] - 0.5
                or bounds[2] > bbox[2] + 0.5
                or bounds[3] > bbox[3] + 0.5
            ):
                raise InspectionError(f"Text outside the visible page on page {number}.")
            if bounds[2] - bounds[0] < 0.1 or bounds[3] - bounds[1] < 0.5:
                raise InspectionError(f"Degenerate or very small text on page {number}.")
            box = _pixel_box(page, bounds, image.size)
            if box[0] >= box[2] or box[1] >= box[3]:
                raise InspectionError(f"Off-page text on page {number}.")
            with image.crop(box) as region:
                extrema = region.getextrema()
                if all(high - low < 3 for low, high in extrema):
                    raise InspectionError(f"Text with no visible contrast on page {number}.")
            text_boxes.append(bounds)
        return normalized_text(textpage.get_text_range())


def inspect_input(source, limits, *, profile):
    """Inspect using a renderer independent of Ghostscript/qpdf."""
    texts, dimensions = [], []
    total_pixels = 0
    with pdfium.PdfDocument(source) as document:
        if len(document) > limits.max_pages:
            raise LimitError("Page limit exceeded.")
        for index in range(len(document)):
            with closing(document[index]) as page:
                with checked_image(page, 144, limits) as image:
                    total_pixels += image.width * image.height
                    if total_pixels > limits.max_total_pixels:
                        raise LimitError("Total rendered pixel limit exceeded.")
                    if profile == "vector":
                        texts.append(inspect_visibility(page, image, limits, index + 1))
                    else:
                        texts.append("")
                    dimensions.append(list(page.get_size()))
    return texts, dimensions


def compare_documents(source, candidate, limits, *, profile, dpi=144):
    """Render both with PDFium; check every tile rather than page-wide mean."""
    results = []
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(candidate) as output:
        if len(original) != len(output):
            raise InspectionError("Independent page-count mismatch.")
        total_pixels = 0
        for index in range(len(original)):
            with closing(original[index]) as before, closing(output[index]) as after:
                if any(abs(a - b) > 0.02 for a, b in zip(before.get_size(), after.get_size())):
                    raise InspectionError(f"Page geometry changed on page {index + 1}.")
                with (
                    checked_image(before, dpi, limits) as a,
                    checked_image(after, dpi, limits) as b,
                ):
                    if a.size != b.size:
                        raise InspectionError(f"Rendered dimensions changed on page {index + 1}.")
                    total_pixels += a.width * a.height
                    if total_pixels > limits.max_total_pixels:
                        raise LimitError("Total comparison pixel limit exceeded.")
                    with ImageChops.difference(a, b) as difference:
                        global_mean = max(ImageStat.Stat(difference).mean)
                        worst_tile = 0.0
                        for y in range(0, a.height, 32):
                            for x in range(0, a.width, 32):
                                with difference.crop(
                                    (x, y, min(x + 32, a.width), min(y + 32, a.height))
                                ) as tile:
                                    worst_tile = max(worst_tile, max(ImageStat.Stat(tile).mean))
                    # Rejected differences need investigation, never automatic acceptance.
                    if global_mean > 1.0 or worst_tile > 12.0:
                        raise InspectionError(
                            f"Rendered appearance changed on page {index + 1} (tile error {worst_tile:.2f})."
                        )
                    if profile == "vector":
                        with (
                            closing(before.get_textpage()) as ta,
                            closing(after.get_textpage()) as tb,
                        ):
                            if normalized_text(ta.get_text_range()) != normalized_text(
                                tb.get_text_range()
                            ):
                                raise InspectionError(
                                    f"Extractable text changed on page {index + 1}."
                                )
                        inspect_visibility(after, b, limits, index + 1)
                    else:
                        with closing(after.get_textpage()) as text:
                            if text.count_chars():
                                raise InspectionError("Raster output unexpectedly contains text.")
                    results.append(
                        {
                            "page": index + 1,
                            "mean_error": round(global_mean, 6),
                            "worst_tile_error": round(worst_tile, 6),
                        }
                    )
    return results
