"""Opt-in lossless image-only profile; no source objects are copied."""

import secrets
from contextlib import closing

import pikepdf
import pypdfium2 as pdfium

from .inspection import checked_image
from .limits import LimitError


def build_raster(source, destination, limits, *, dpi):
    total_pixels = 0
    with pdfium.PdfDocument(source) as original, pikepdf.Pdf.new() as clean:
        for index in range(len(original)):
            with closing(original[index]) as page:
                # qpdf serializes page coordinates to six decimal places.
                # Use that same canonical precision for the image matrix.
                width, height = (round(value, 6) for value in page.get_size())
                with checked_image(page, dpi, limits) as pixels:
                    total_pixels += pixels.width * pixels.height
                    if total_pixels > limits.max_total_pixels:
                        raise LimitError("Total raster pixel limit exceeded.")
                    outpage = clean.add_blank_page(page_size=(width, height))
                    image = clean.make_stream(pixels.tobytes())
                    for key, value in {
                        "/Type": pikepdf.Name("/XObject"),
                        "/Subtype": pikepdf.Name("/Image"),
                        "/Width": pixels.width,
                        "/Height": pixels.height,
                        "/ColorSpace": pikepdf.Name("/DeviceRGB"),
                        "/BitsPerComponent": 8,
                    }.items():
                        image[key] = value
                    outpage.obj["/Resources"] = pikepdf.Dictionary(
                        XObject=pikepdf.Dictionary(Im0=image)
                    )
                    outpage.obj["/Contents"] = clean.make_stream(
                        f"%pdfblinder-instance:{secrets.token_hex(16)}\nq\n{width:.8f} 0 0 {height:.8f} 0 0 cm\n/Im0 Do\nQ\n".encode()
                    )
        clean.trailer["/ID"] = pikepdf.Array(
            [pikepdf.String(secrets.token_bytes(16)), pikepdf.String(secrets.token_bytes(16))]
        )
        clean.save(
            destination,
            deterministic_id=True,
            min_version="1.7",
            fix_metadata_version=False,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        return len(clean.pages)
