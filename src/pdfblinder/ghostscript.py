"""Ghostscript reconstruction into a temporary intermediate PDF."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Iterator


class GhostscriptError(RuntimeError):
    """Ghostscript could not reconstruct the input."""


def find_ghostscript(executable: str | None = None) -> str:
    candidates = (
        [executable] if executable is not None
        else ["gs", "gswin64c", "gswin32c"]
    )
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise GhostscriptError(
        "Ghostscript was not found. Install it or specify its executable."
    )


@contextmanager
def reconstructed_pdf(
    source: Path,
    *,
    executable: str | None = None,
    timeout: float = 120,
) -> Iterator[Path]:
    """Yield an intermediate PDF; remove temporary files on exit.

    This stage alone does not establish anonymity.
    """
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise ValueError("Input must be a regular file.")
    if timeout <= 0:
        raise ValueError("Timeout must be positive.")

    gs = find_ghostscript(executable)
    with TemporaryDirectory(prefix="pdfblinder-") as directory:
        output = Path(directory) / "reconstructed.pdf"
        command = [
            gs,
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-dPDFSTOPONERROR",
            "-dPDFSTOPONWARNING",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            "-dPreserveAnnots=false",
            "-dShowAnnots=false",
            "-dPreserveMarkedContent=false",
            "-dDownsampleColorImages=false",
            "-dDownsampleGrayImages=false",
            "-dDownsampleMonoImages=false",
            f"-sOutputFile={output}",
            "-f",
            str(source),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhostscriptError(
                f"Ghostscript exceeded the {timeout:g}-second timeout."
            ) from exc
        except OSError as exc:
            raise GhostscriptError(
                f"Could not execute Ghostscript: {exc}"
            ) from exc

        if result.returncode != 0:
            details = (result.stdout + result.stderr).decode(
                "utf-8", errors="replace"
            ).strip()
            raise GhostscriptError(
                f"Ghostscript failed with exit code {result.returncode}.\n"
                f"{details[-8000:]}"
            )
        if not output.is_file() or output.stat().st_size == 0:
            raise GhostscriptError("Ghostscript produced no PDF output.")

        yield output
