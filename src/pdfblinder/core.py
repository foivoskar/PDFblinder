"""Complete PDFblinder processing pipeline."""

import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import pikepdf

from .ghostscript import reconstructed_pdf
from .sanitize import sanitize_intermediate
from .verify import VerificationError, verify_pdf


class InputError(ValueError):
    """The input is unsupported or unsuitable for processing."""


def blind_pdf(
    source: Path,
    destination: Path,
    *,
    executable: str | None = None,
    timeout: float = 120,
) -> int:
    """Create a verified output without overwriting existing files.

    Returns the page count. Structural sanitation does not remove
    identifying visible content or guarantee complete anonymity.
    """
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().absolute()

    if not source.is_file():
        raise InputError("Input must be a regular file.")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Output already exists: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(
            f"Output directory does not exist: {destination.parent}"
        )

    with TemporaryDirectory(prefix="pdfblinder-job-") as directory:
        work = Path(directory)
        snapshot = work / "input.pdf"
        candidate = work / "candidate.pdf"
        shutil.copyfile(source, snapshot)

        with pikepdf.Pdf.open(
            snapshot, attempt_recovery=False
        ) as original:
            if original.is_encrypted:
                raise InputError("Encrypted input PDFs are not supported.")
            page_count = len(original.pages)
            if page_count == 0:
                raise InputError("Input PDF contains no pages.")
            if "/AcroForm" in original.Root:
                raise InputError(
                    "PDFs with forms or signature fields are not supported. "
                    "Export a static PDF first and check its appearance."
                )
            original_ids = tuple(
                bytes(identifier)
                for identifier in original.trailer.get("/ID", [])
            )

        with reconstructed_pdf(
            snapshot, executable=executable, timeout=timeout
        ) as intermediate:
            with candidate.open("xb") as stream:
                reconstructed_count = sanitize_intermediate(
                    intermediate, stream
                )

        if reconstructed_count != page_count:
            raise VerificationError(
                "Reconstruction changed the number of pages."
            )

        verify_pdf(
            candidate,
            expected_pages=page_count,
            original_ids=original_ids,
        )

        # Exclusive creation also prevents overwriting a file that
        # appeared after the initial destination check.
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                with candidate.open("rb") as verified:
                    shutil.copyfileobj(verified, output)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    return page_count
