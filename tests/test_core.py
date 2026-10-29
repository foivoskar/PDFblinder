import subprocess

import pikepdf
import pytest

from pdfblinder import core
from pdfblinder.core import InputError, blind_pdf
from pdfblinder.ghostscript import GhostscriptError, find_ghostscript
from pdfblinder.verify import VerificationError, verify_pdf


@pytest.fixture
def input_pdf(tmp_path):
    source = tmp_path / "original with spaces.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type1"),
                BaseFont=pikepdf.Name("/Helvetica"),
            )
        )
        page.obj["/Resources"] = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.obj["/Contents"] = pdf.make_stream(
            b"BT /F1 12 Tf 30 100 Td (Visible review text) Tj ET\n"
        )
        pdf.docinfo["/Author"] = "Private Author Marker"
        pdf.save(source)
    return source


def test_complete_pipeline_preserves_text(input_pdf, tmp_path):
    output = tmp_path / "blinded.pdf"
    original_bytes = input_pdf.read_bytes()
    with pikepdf.Pdf.open(input_pdf) as pdf:
        original_ids = tuple(bytes(item) for item in pdf.trailer["/ID"])

    assert blind_pdf(input_pdf, output) == 1
    assert input_pdf.read_bytes() == original_bytes
    assert verify_pdf(output, expected_pages=1, original_ids=original_ids) == 1

    result = subprocess.run(
        [
            find_ghostscript(),
            "-q",
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=txtwrite",
            "-sOutputFile=-",
            "-f",
            str(output),
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert b"Visible review text" in result.stdout
    assert b"Private Author Marker" not in result.stdout


def test_existing_output_is_preserved(input_pdf, tmp_path):
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"Do not overwrite")

    with pytest.raises(FileExistsError):
        blind_pdf(input_pdf, output)

    assert output.read_bytes() == b"Do not overwrite"


def test_input_cannot_be_overwritten(input_pdf):
    original_bytes = input_pdf.read_bytes()
    with pytest.raises(FileExistsError):
        blind_pdf(input_pdf, input_pdf)
    assert input_pdf.read_bytes() == original_bytes


def test_verification_failure_creates_no_output(input_pdf, tmp_path, monkeypatch):
    output = tmp_path / "rejected.pdf"

    def reject(*args, **kwargs):
        raise VerificationError("Simulated verification failure")

    monkeypatch.setattr(core, "_supervise", reject)
    with pytest.raises(VerificationError, match="Simulated"):
        blind_pdf(input_pdf, output)

    assert not output.exists()


def test_missing_ghostscript_creates_no_output(input_pdf, tmp_path):
    output = tmp_path / "failed.pdf"
    with pytest.raises(GhostscriptError):
        blind_pdf(
            input_pdf,
            output,
            executable="pdfblinder-nonexistent-executable",
        )
    assert not output.exists()


def test_rejects_encrypted_input(tmp_path):
    source = tmp_path / "encrypted.pdf"
    output = tmp_path / "output.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(
            source,
            encryption=pikepdf.Encryption(owner="owner", user=""),
        )
    with pytest.raises(InputError, match="Encrypted"):
        blind_pdf(source, output)
    assert not output.exists()


def test_rejects_form_input(tmp_path):
    source = tmp_path / "form.pdf"
    output = tmp_path / "output.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.Root["/AcroForm"] = pikepdf.Dictionary(Fields=pikepdf.Array())
        pdf.save(source)
    with pytest.raises(InputError, match="forms"):
        blind_pdf(source, output)
    assert not output.exists()


def test_rejects_empty_input(tmp_path):
    source = tmp_path / "empty.pdf"
    output = tmp_path / "output.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.save(source)
    with pytest.raises(InputError, match="no pages"):
        blind_pdf(source, output)
    assert not output.exists()
