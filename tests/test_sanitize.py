from io import BytesIO

import pikepdf
import pytest

from pdfblinder.sanitize import (
    SanitationError,
    sanitize_intermediate,
)


def test_removes_auxiliary_data_and_preserves_content(tmp_path):
    source = tmp_path / "intermediate.pdf"
    content = b"0 0 20 30 re f\n/Fm0 Do\n"
    form_content = b"q Q\n"

    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        page.obj["/Contents"] = pdf.make_stream(content)
        pdf.docinfo["/Author"] = "Identifying Author"
        pdf.Root["/Metadata"] = pdf.make_stream(
            b"<metadata>Identifying Author</metadata>"
        )
        pdf.Root["/OpenAction"] = pikepdf.Dictionary(
            S=pikepdf.Name("/JavaScript"),
            JS=pikepdf.String("Identifying Author"),
        )
        pdf.Root["/Names"] = pikepdf.Dictionary(
            EmbeddedFiles=pikepdf.Dictionary(
                Names=pikepdf.Array([
                    pikepdf.String("private.txt"),
                    pikepdf.Dictionary(
                        Type=pikepdf.Name("/Filespec"),
                        F=pikepdf.String("private.txt"),
                        EF=pikepdf.Dictionary(
                            F=pdf.make_stream(b"Private attachment")
                        ),
                    ),
                ])
            )
        )
        page.obj["/PieceInfo"] = pikepdf.Dictionary(
            Private=pikepdf.String("Identifying Author")
        )
        page.obj["/Annots"] = pikepdf.Array([
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Annot"),
                Subtype=pikepdf.Name("/Text"),
                Rect=pikepdf.Array([0, 0, 10, 10]),
                Contents=pikepdf.String("Private comment"),
                T=pikepdf.String("Identifying Author"),
            )
        ])
        form = pdf.make_stream(form_content)
        form["/Type"] = pikepdf.Name("/XObject")
        form["/Subtype"] = pikepdf.Name("/Form")
        form["/BBox"] = pikepdf.Array([0, 0, 10, 10])
        form["/Resources"] = pikepdf.Dictionary()
        form["/PieceInfo"] = pikepdf.Dictionary(
            Private=pikepdf.String("Nested identifying data")
        )
        form["/Metadata"] = pdf.make_stream(b"Nested metadata")
        page.obj["/Resources"] = pikepdf.Dictionary(
            XObject=pikepdf.Dictionary(Fm0=form)
        )
        pdf.save(source)

    original_bytes = source.read_bytes()
    output = BytesIO()
    assert sanitize_intermediate(source, output) == 1
    output.seek(0)

    with pikepdf.Pdf.open(output) as clean:
        assert "/Info" not in clean.trailer
        assert set(clean.Root.keys()) == {"/Type", "/Pages"}
        assert len(clean.pages) == 1
        page = clean.pages[0]
        assert "/Annots" not in page.obj
        assert "/PieceInfo" not in page.obj
        assert list(page.mediabox) == [0, 0, 300, 400]
        assert page.obj["/Contents"].read_bytes() == content
        form = page.obj["/Resources"]["/XObject"]["/Fm0"]
        assert "/Metadata" not in form
        assert "/PieceInfo" not in form
        assert form.read_bytes() == form_content

    assert source.read_bytes() == original_bytes


def test_rejects_empty_pdf(tmp_path):
    source = tmp_path / "empty.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.save(source)

    with pytest.raises(SanitationError, match="no pages"):
        sanitize_intermediate(source, BytesIO())


def test_rejects_encrypted_intermediate(tmp_path):
    source = tmp_path / "encrypted.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(
            source,
            encryption=pikepdf.Encryption(
                owner="test-owner", user=""
            ),
        )

    with pytest.raises(SanitationError, match="Encrypted"):
        sanitize_intermediate(source, BytesIO())
