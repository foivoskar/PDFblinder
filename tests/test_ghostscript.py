import pikepdf
import pytest

from pdfblinder.ghostscript import (
    GhostscriptError,
    find_ghostscript,
    reconstructed_pdf,
)


def test_missing_executable():
    with pytest.raises(GhostscriptError, match="not found"):
        find_ghostscript("pdfblinder-nonexistent-executable")


def test_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        with reconstructed_pdf(tmp_path / "missing.pdf"):
            pytest.fail("Missing input must not produce output.")


def test_reconstruction_and_cleanup(tmp_path):
    source = tmp_path / "original with spaces.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400))
        pdf.add_blank_page(page_size=(500, 600))
        pdf.docinfo["/Author"] = "Original Author"
        pdf.save(source)

    original_bytes = source.read_bytes()

    with reconstructed_pdf(source) as intermediate:
        assert intermediate.is_file()
        assert intermediate != source
        with pikepdf.Pdf.open(intermediate) as pdf:
            assert len(pdf.pages) == 2
            for page, expected in zip(pdf.pages, [(300, 400), (500, 600)]):
                box = [float(value) for value in page.mediabox]
                assert box[2] - box[0] == pytest.approx(expected[0])
                assert box[3] - box[1] == pytest.approx(expected[1])
        assert source.read_bytes() == original_bytes
        temporary_directory = intermediate.parent

    assert not intermediate.exists()
    assert not temporary_directory.exists()
    assert source.read_bytes() == original_bytes
