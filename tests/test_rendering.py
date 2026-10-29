import subprocess

import pikepdf
from PIL import Image, ImageChops, ImageStat

from pdfblinder.core import blind_pdf
from pdfblinder.ghostscript import find_ghostscript


def render_pdf(source, destination):
    subprocess.run(
        [
            find_ghostscript(),
            "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
            "-dShowAnnots=false",
            "-sDEVICE=png16m",
            "-r144",
            "-dTextAlphaBits=4",
            "-dGraphicsAlphaBits=4",
            f"-sOutputFile={destination}",
            "-f", str(source),
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )


def test_reconstruction_preserves_rendered_appearance(tmp_path):
    source = tmp_path / "original.pdf"
    output = tmp_path / "blinded.pdf"

    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        font = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type1"),
            BaseFont=pikepdf.Name("/Helvetica"),
        ))
        page.obj["/Resources"] = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(F1=font)
        )
        page.obj["/Contents"] = pdf.make_stream(
            b"0.1 0.3 0.7 rg 25 250 250 100 re f\n"
            b"1 0.8 0.2 rg 50 275 80 50 re f\n"
            b"0 0 0 RG 2 w 25 220 m 275 220 l S\n"
            b"0 0 0 rg\n"
            b"BT /F1 18 Tf 25 180 Td (PDFblinder review) Tj ET\n"
            b"BT /F1 12 Tf 25 150 Td (Text and vector graphics) Tj ET\n"
        )
        pdf.docinfo["/Author"] = "Private Author"
        pdf.save(source)

    blind_pdf(source, output)
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    render_pdf(source, before)
    render_pdf(output, after)

    with Image.open(before) as original, Image.open(after) as blinded:
        assert original.size == blinded.size
        assert original.mode == blinded.mode == "RGB"
        difference = ImageChops.difference(original, blinded)
        channel_errors = ImageStat.Stat(difference).mean
        assert max(channel_errors) <= 0.5, (
            f"Rendered appearance changed: {channel_errors}"
        )
