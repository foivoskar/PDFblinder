import pikepdf
import pytest

from pdfblinder.sanitize import sanitize_intermediate
from pdfblinder.verify import VerificationError, verify_pdf


@pytest.fixture
def clean_pdf(tmp_path):
    source = tmp_path / "intermediate.pdf"
    output = tmp_path / "clean.pdf"

    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400))
        pdf.docinfo["/Author"] = "Original Author"
        pdf.save(source)

    with output.open("xb") as stream:
        sanitize_intermediate(source, stream)

    return output


def test_accepts_sanitized_pdf(clean_pdf):
    assert verify_pdf(clean_pdf, expected_pages=1) == 1


def test_rejects_wrong_page_count(clean_pdf):
    with pytest.raises(VerificationError, match="page count"):
        verify_pdf(clean_pdf, expected_pages=2)


def test_rejects_reused_identifier(clean_pdf):
    with pikepdf.Pdf.open(clean_pdf) as pdf:
        original_ids = tuple(
            bytes(identifier) for identifier in pdf.trailer["/ID"]
        )

    with pytest.raises(VerificationError, match="identifier remains"):
        verify_pdf(
            clean_pdf,
            expected_pages=1,
            original_ids=original_ids,
        )


@pytest.mark.parametrize(
    "contamination",
    ["author", "catalog_metadata", "annotation", "nested_metadata"],
)
def test_rejects_contaminated_pdf(clean_pdf, tmp_path, contamination):
    contaminated = tmp_path / "contaminated.pdf"

    with pikepdf.Pdf.open(clean_pdf) as pdf:
        if contamination == "author":
            pdf.docinfo["/Author"] = "Identifying Author"
        elif contamination == "catalog_metadata":
            pdf.Root["/Metadata"] = pdf.make_stream(b"Private metadata")
        elif contamination == "annotation":
            pdf.pages[0].obj["/Annots"] = pikepdf.Array([
                pikepdf.Dictionary(
                    Type=pikepdf.Name("/Annot"),
                    Subtype=pikepdf.Name("/Text"),
                    Rect=pikepdf.Array([0, 0, 10, 10]),
                    Contents=pikepdf.String("Private comment"),
                )
            ])
        else:
            pdf.pages[0].obj["/Group"] = pikepdf.Dictionary(
                Type=pikepdf.Name("/Group"),
                S=pikepdf.Name("/Transparency"),
                CS=pikepdf.Name("/DeviceRGB"),
                Metadata=pdf.make_stream(b"Nested private metadata"),
            )

        pdf.save(contaminated, fix_metadata_version=False)

    with pytest.raises(VerificationError):
        verify_pdf(contaminated, expected_pages=1)
