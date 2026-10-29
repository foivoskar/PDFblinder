"""Regression corpus for privacy, preservation, limits and audit publication."""

import hashlib
import json
import secrets
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest

from pdfblinder import core
from pdfblinder.core import InputError, ProcessingError, blind_pdf
from pdfblinder.independent import verify_independently
from pdfblinder.inspection import InspectionError, compare_documents
from pdfblinder.limits import LimitError, Limits
from pdfblinder.sanitize import sanitize_intermediate
from pdfblinder.verify import verify_pdf


@pytest.fixture
def make_pdf(tmp_path):
    def create(
        commands=b"BT /F1 12 Tf 30 300 Td (Visible review text) Tj ET\n",
        *,
        rotation=0,
        crop=None,
        opacity=None,
        nested=False,
    ):
        path = tmp_path / (secrets.token_hex(4) + ".pdf")
        with pikepdf.Pdf.new() as pdf:
            page = pdf.add_blank_page(page_size=(300, 400))
            font = pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/Font"),
                    Subtype=pikepdf.Name("/Type1"),
                    BaseFont=pikepdf.Name("/Helvetica"),
                )
            )
            resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            if opacity is not None:
                resources["/ExtGState"] = pikepdf.Dictionary(
                    GS0=pikepdf.Dictionary(ca=opacity, CA=opacity)
                )
            if nested:
                form = pdf.make_stream(commands)
                form["/Type"] = pikepdf.Name("/XObject")
                form["/Subtype"] = pikepdf.Name("/Form")
                form["/BBox"] = pikepdf.Array([0, 0, 300, 400])
                form["/Resources"] = resources
                page.obj["/Resources"] = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm=form))
                page.obj["/Contents"] = pdf.make_stream(b"/Fm Do")
            else:
                page.obj["/Resources"] = resources
                page.obj["/Contents"] = pdf.make_stream(commands)
            if rotation:
                page.obj["/Rotate"] = rotation
            if crop is not None:
                page.obj["/CropBox"] = pikepdf.Array(crop)
            pdf.docinfo["/Author"] = "Private Author Marker"
            pdf.save(path)
        return path

    return create


@pytest.mark.parametrize(
    "commands,match",
    [
        (b"BT /F1 12 Tf 3 Tr 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", "Invisible"),
        (b"BT /F1 12 Tf 7 Tr 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", "Invisible"),
        (b"1 1 1 rg BT /F1 12 Tf 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", "contrast"),
        (b"BT /F1 12 Tf 500 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", "outside"),
        (b"BT /F1 0.1 Tf 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", "small"),
        (
            b"BT /F1 12 Tf 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET 1 1 1 rg 0 250 300 100 re f",
            "contrast|covered",
        ),
    ],
)
def test_rejects_known_hidden_text(make_pdf, tmp_path, commands, match):
    source = make_pdf(commands)
    output = tmp_path / "output.pdf"
    with pytest.raises(ProcessingError, match=match):
        blind_pdf(source, output)
    assert not output.exists()
    assert not Path(str(output) + ".audit.json").exists()


def test_rejects_transparent_text(make_pdf, tmp_path):
    source = make_pdf(b"/GS0 gs BT /F1 12 Tf 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", opacity=0)
    with pytest.raises(ProcessingError, match="Transparent"):
        blind_pdf(source, tmp_path / "output.pdf")


def test_rejects_invisible_text_in_form(make_pdf, tmp_path):
    source = make_pdf(b"BT /F1 12 Tf 3 Tr 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET", nested=True)
    with pytest.raises(ProcessingError, match="Invisible"):
        blind_pdf(source, tmp_path / "output.pdf")


def test_raster_drops_hidden_text_and_source_fonts(make_pdf, tmp_path):
    source = make_pdf(
        b"BT /F1 12 Tf 30 300 Td (Visible review text) Tj ET BT /F1 12 Tf 3 Tr 30 200 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET"
    )
    output = tmp_path / "raster.pdf"
    assert blind_pdf(source, output, profile="raster") == 1
    with (
        pdfium.PdfDocument(output) as pdf,
        closing(pdf[0]) as page,
        closing(page.get_textpage()) as text,
    ):
        assert text.count_chars() == 0
    with pikepdf.Pdf.open(output) as pdf:
        assert "/Font" not in pdf.pages[0].obj["/Resources"]
    verify_independently(output, Limits(), expected_pages=1, profile="raster")
    report = json.loads(Path(str(output) + ".audit.json").read_text())
    assert report["human_review"] == "pending"
    assert report["approved_for_submission"] is False
    assert report["profile"] == "raster"


def test_vector_remains_default_and_audit_private(make_pdf, tmp_path):
    source = make_pdf()
    original = source.read_bytes()
    output = tmp_path / "vector.pdf"
    blind_pdf(source, output)
    audit_path = Path(str(output) + ".audit.json")
    audit_text = audit_path.read_text()
    report = json.loads(audit_text)
    assert report["profile"] == "vector"
    assert report["input_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert report["human_review"] == "pending"
    assert "Private Author Marker" not in audit_text
    assert str(source) not in audit_text
    assert source.read_bytes() == original
    with (
        pdfium.PdfDocument(output) as pdf,
        closing(pdf[0]) as page,
        closing(page.get_textpage()) as text,
    ):
        assert "Visible review text" in text.get_text_range()
    if sys.platform != "win32":
        assert output.stat().st_mode & 0o077 == 0
        assert audit_path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("name", ["A", "AA", "AF", "JS", "Metadata"])
def test_resource_aliases_not_deleted(tmp_path, name):
    source = tmp_path / "named-resource.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type1"),
                BaseFont=pikepdf.Name("/Helvetica"),
            )
        )
        fonts = pikepdf.Dictionary()
        fonts["/" + name] = font
        page.obj["/Resources"] = pikepdf.Dictionary(Font=fonts)
        page.obj["/Contents"] = pdf.make_stream(
            f"BT /{name} 12 Tf 30 300 Td (Visible) Tj ET".encode()
        )
        pdf.save(source)
    clean = BytesIO()
    sanitize_intermediate(source, clean)
    clean.seek(0)
    with pikepdf.Pdf.open(clean) as pdf:
        assert "/" + name in pdf.pages[0].obj["/Resources"]["/Font"]
    clean.seek(0)
    verify_pdf(clean, expected_pages=1)
    clean.seek(0)
    verify_independently(clean, Limits(), expected_pages=1, profile="vector")


def test_type3_A_preserved_and_rendered(tmp_path):
    source, output = tmp_path / "type3.pdf", tmp_path / "clean.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        glyph = pdf.make_stream(b"600 0 0 0 600 700 d1 0 0 600 700 re f")
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type3"),
                FontBBox=pikepdf.Array([0, 0, 600, 700]),
                FontMatrix=pikepdf.Array([0.001, 0, 0, 0.001, 0, 0]),
                CharProcs=pikepdf.Dictionary(A=glyph),
                Encoding=pikepdf.Dictionary(
                    Type=pikepdf.Name("/Encoding"),
                    Differences=pikepdf.Array([65, pikepdf.Name("/A")]),
                ),
                FirstChar=65,
                LastChar=65,
                Widths=pikepdf.Array([600]),
                Resources=pikepdf.Dictionary(),
            )
        )
        page.obj["/Resources"] = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.obj["/Contents"] = pdf.make_stream(b"BT /F1 24 Tf 30 300 Td (A) Tj ET")
        pdf.save(source)
    with output.open("wb") as stream:
        sanitize_intermediate(source, stream)
    with pikepdf.Pdf.open(output) as pdf:
        assert "/A" in pdf.pages[0].obj["/Resources"]["/Font"]["/F1"]["/CharProcs"]
    compare_documents(source, output, Limits(), profile="vector")
    blind_pdf(source, tmp_path / "complete.pdf")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_text_geometry(make_pdf, tmp_path, rotation):
    source = make_pdf(rotation=rotation)
    blind_pdf(source, tmp_path / "rotated.pdf")


def test_cropped_page_geometry(make_pdf, tmp_path):
    source = make_pdf(crop=[10, 10, 290, 390])
    blind_pdf(source, tmp_path / "cropped.pdf")


@pytest.mark.parametrize(
    "limit,match",
    [
        (replace(Limits(), max_input_bytes=10), "size limit"),
        (replace(Limits(), max_work_bytes=10), "size limit"),
        (replace(Limits(), max_memory_bytes=1), "memory limit"),
        (replace(Limits(), max_page_pixels=100), "pixel limit"),
        (replace(Limits(), max_objects=1), "object limit"),
    ],
)
def test_limits_fail_without_publication(make_pdf, tmp_path, limit, match):
    source = make_pdf()
    output = tmp_path / "limited.pdf"
    with pytest.raises(LimitError, match=match):
        blind_pdf(source, output, limits=limit)
    assert not output.exists()
    assert not Path(str(output) + ".audit.json").exists()


def test_timeout_includes_all_processing(make_pdf, tmp_path):
    output = tmp_path / "timed-out.pdf"
    with pytest.raises(LimitError, match="time limit"):
        blind_pdf(make_pdf(), output, timeout=0.001)
    assert not output.exists()


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1])
def test_api_rejects_invalid_timeout(make_pdf, tmp_path, timeout):
    with pytest.raises(ValueError):
        blind_pdf(make_pdf(), tmp_path / "output.pdf", timeout=timeout)


def test_existing_audit_not_overwritten(make_pdf, tmp_path):
    output = tmp_path / "out.pdf"
    report = Path(str(output) + ".audit.json")
    report.write_text("Private existing log")
    with pytest.raises(FileExistsError):
        blind_pdf(make_pdf(), output)
    assert report.read_text() == "Private existing log"
    assert not output.exists()


def test_failed_pdf_publication_rolls_back_audit(make_pdf, tmp_path, monkeypatch):
    original_publish = core._publish

    def publish(source, destination):
        if destination.suffix == ".pdf":
            raise OSError("simulated filesystem failure")
        original_publish(source, destination)

    monkeypatch.setattr(core, "_publish", publish)
    output = tmp_path / "output.pdf"
    with pytest.raises(OSError, match="simulated"):
        blind_pdf(make_pdf(), output)
    assert not output.exists()
    assert not Path(str(output) + ".audit.json").exists()


def test_independent_parser_catches_separate_policy_field(make_pdf, tmp_path):
    source = make_pdf()
    candidate = tmp_path / "clean.pdf"
    with candidate.open("wb") as stream:
        sanitize_intermediate(source, stream)
    tampered = tmp_path / "tampered.pdf"
    with pikepdf.Pdf.open(candidate) as pdf:
        pdf.pages[0].obj["/Group"] = pikepdf.Dictionary(
            Type=pikepdf.Name("/Group"),
            S=pikepdf.Name("/Transparency"),
            Author=pikepdf.String("Private Author"),
        )
        pdf.save(tampered)
    with pytest.raises(InspectionError, match="auxiliary"):
        verify_independently(tampered, Limits(), expected_pages=1, profile="vector")


def test_independent_render_detects_small_local_change(make_pdf):
    original = make_pdf(b"0 0 0 rg 30 300 15 15 re f")
    missing = make_pdf(b"q Q")
    with pytest.raises(InspectionError, match="appearance"):
        compare_documents(original, missing, Limits(), profile="vector")


def test_embedded_unicode_and_math_font(tmp_path):
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    pdfmetrics.registerFont(TTFont("RegressionVera", str(font_path), asciiReadable=False))
    source = tmp_path / "unicode.pdf"
    document = canvas.Canvas(str(source), pagesize=(300, 400))
    document.setFont("RegressionVera", 14)
    document.drawString(20, 330, "École — façade — naïve")
    document.drawString(20, 300, "Scientific symbols: ± × ÷ ≤ ≥")
    document.setFont("Symbol", 14)
    document.drawString(20, 270, "α β γ Δ Σ Ω")
    document.save()
    blind_pdf(source, tmp_path / "unicode-output.pdf")


def test_rgb_image_and_transparent_vector_artwork(make_pdf, tmp_path):
    source = make_pdf(
        b"q 120 0 0 60 30 100 cm /Im0 Do Q\n/GS0 gs 0.2 0.4 0.8 rg 30 220 120 60 re f\n0 0 0 rg BT /F1 12 Tf 30 320 Td (Figure caption) Tj ET",
        opacity=0.5,
    )
    updated = tmp_path / "artwork.pdf"
    with pikepdf.Pdf.open(source) as pdf:
        pixels = bytes(
            [component for y in range(16) for x in range(32) for component in (x * 8, y * 16, 128)]
        )
        image = pdf.make_stream(pixels)
        for key, value in {
            "/Type": pikepdf.Name("/XObject"),
            "/Subtype": pikepdf.Name("/Image"),
            "/Width": 32,
            "/Height": 16,
            "/ColorSpace": pikepdf.Name("/DeviceRGB"),
            "/BitsPerComponent": 8,
        }.items():
            image[key] = value
        pdf.pages[0].obj["/Resources"]["/XObject"] = pikepdf.Dictionary(Im0=image)
        # Restore opaque text after transparent artwork.
        contents = (
            pdf.pages[0]
            .obj["/Contents"]
            .read_bytes()
            .replace(b"0 0 0 rg BT", b"/GS1 gs 0 0 0 rg BT")
        )
        pdf.pages[0].obj["/Resources"]["/ExtGState"]["/GS1"] = pikepdf.Dictionary(ca=1, CA=1)
        pdf.pages[0].obj["/Contents"] = pdf.make_stream(contents)
        pdf.save(updated)
    blind_pdf(updated, tmp_path / "figure-output.pdf")


def test_multiple_pages_and_page_cap(tmp_path):
    source = tmp_path / "two-pages.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400))
        pdf.add_blank_page(page_size=(400, 300))
        pdf.save(source)
    assert blind_pdf(source, tmp_path / "two-pages-output.pdf") == 2
    with pytest.raises(LimitError, match="Page"):
        blind_pdf(source, tmp_path / "limited.pdf", limits=replace(Limits(), max_pages=1))


def test_same_second_reprocessing_generates_new_identifiers(make_pdf, tmp_path):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    blind_pdf(make_pdf(), first)
    blind_pdf(first, second)
    with pikepdf.Pdf.open(first) as a, pikepdf.Pdf.open(second) as b:
        assert not set(map(bytes, a.trailer["/ID"])) & set(map(bytes, b.trailer["/ID"]))


def test_raster_rejects_extra_hidden_content(make_pdf, tmp_path):
    output = tmp_path / "raster.pdf"
    blind_pdf(make_pdf(), output, profile="raster")
    tampered = tmp_path / "tampered.pdf"
    with pikepdf.Pdf.open(output) as pdf:
        pdf.pages[0].obj["/Contents"].write(
            pdf.pages[0].obj["/Contents"].read_bytes() + b"%secret additional payload"
        )
        pdf.save(tampered)
    with pytest.raises(InspectionError, match="noncanonical"):
        verify_independently(tampered, Limits(), expected_pages=1, profile="raster")


def test_cli_rejects_hidden_text_without_logging_it(make_pdf, tmp_path):
    source = make_pdf(b"BT /F1 12 Tf 3 Tr 30 300 Td (PRIVATE_AUTHOR_SENTINEL) Tj ET")
    result = subprocess.run(
        [sys.executable, "-m", "pdfblinder", str(source), str(tmp_path / "out.pdf")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "Invisible" in result.stderr
    assert "PRIVATE_AUTHOR_SENTINEL" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr


def test_resource_monitor_permission_denied_fails_closed(make_pdf, tmp_path, monkeypatch):
    class UnreadableProcess:
        def __init__(self, pid):
            pass

        def children(self, recursive):
            raise PermissionError("OS resource monitor denied")

    monkeypatch.setattr(core.psutil, "Process", UnreadableProcess)
    with pytest.raises(LimitError, match="denied"):
        blind_pdf(make_pdf(), tmp_path / "output.pdf")


def test_publication_cannot_clobber_racing_destination(tmp_path):
    source = tmp_path / "verified"
    source.write_bytes(b"verified")
    destination = tmp_path / "existing"
    destination.write_bytes(b"private original")
    with pytest.raises(FileExistsError):
        core._publish(source, destination)
    assert destination.read_bytes() == b"private original"
    assert not list(tmp_path.glob(".pdfblinder-*"))


def test_alternate_text_requires_investigation(make_pdf, tmp_path):
    source = make_pdf(
        b"/Span << /ActualText (PRIVATE_AUTHOR_SENTINEL) >> BDC BT /F1 12 Tf 30 300 Td (Visible) Tj ET EMC"
    )
    with pytest.raises(InputError, match="Alternate"):
        blind_pdf(source, tmp_path / "output.pdf")


def test_malformed_unicode_cmap_is_rejected(tmp_path):
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    from pdfblinder.ghostscript import GhostscriptError

    path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    pdfmetrics.registerFont(TTFont("InvalidCMapFixture", str(path), asciiReadable=True))
    source = tmp_path / "bad-cmap.pdf"
    document = canvas.Canvas(str(source), pagesize=(300, 400))
    document.setFont("InvalidCMapFixture", 14)
    document.drawString(20, 330, "École — façade — naïve")
    document.save()
    # Construct the malformed CMap explicitly, independent of ReportLab's
    # global font cache or future changes in its default subset generator.
    import re

    malformed = tmp_path / "malformed.pdf"
    with pikepdf.Pdf.open(source) as pdf:
        modified = False
        for font in pdf.pages[0].obj["/Resources"]["/Font"].values():
            if "/ToUnicode" not in font:
                continue
            cmap = font["/ToUnicode"].read_bytes()
            start = re.search(rb"\d+\s+beginbfchar", cmap)
            assert start is not None
            end = cmap.index(b"endbfchar", start.end()) + len(b"endbfchar")
            entries = b"\n".join(f"<{i:02x}> <{i:04x}>".encode() for i in range(101))
            font["/ToUnicode"].write(
                cmap[: start.start()] + b"101 beginbfchar\n" + entries + b"\nendbfchar" + cmap[end:]
            )
            modified = True
        assert modified
        pdf.save(malformed)
    with pytest.raises((InputError, GhostscriptError, ProcessingError)):
        blind_pdf(malformed, tmp_path / "output.pdf")


def test_optional_layers_and_userunit_rejected(make_pdf, tmp_path):
    source = make_pdf()
    for kind in ["layers", "userunit"]:
        changed = tmp_path / (kind + ".pdf")
        with pikepdf.Pdf.open(source) as pdf:
            if kind == "layers":
                pdf.Root["/OCProperties"] = pikepdf.Dictionary(OCGs=pikepdf.Array())
            else:
                pdf.pages[0].obj["/UserUnit"] = 2
            pdf.save(changed)
        with pytest.raises(InputError):
            blind_pdf(changed, tmp_path / (kind + "-out.pdf"))


def test_standard_ligature_actualtext_preserves_text(make_pdf, tmp_path):
    source = make_pdf(b"/Span << /ActualText (fi) >> BDC BT /F1 12 Tf 30 300 Td (fi) Tj ET EMC")
    assert blind_pdf(source, tmp_path / "output.pdf") == 1


@pytest.mark.parametrize("dimensions", [(974.880005, 792), (595.2756, 841.8898)])
def test_fractional_raster_page_dimensions(tmp_path, dimensions):
    source = tmp_path / "fractional.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=dimensions)
        pdf.save(source)
    blind_pdf(source, tmp_path / "output.pdf", profile="raster")
