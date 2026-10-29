"""Ghostscript reconstruction into a temporary intermediate PDF."""

import math
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


class GhostscriptError(RuntimeError):
    """Ghostscript could not reconstruct the input."""


def find_ghostscript(executable: str | None = None) -> str:
    candidates = [executable] if executable is not None else ["gs", "gswin64c", "gswin32c"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise GhostscriptError("Ghostscript was not found. Install it or specify its executable.")


@contextmanager
def reconstructed_pdf(
    source: Path,
    *,
    executable: str | None = None,
    timeout: float = 120,
    work_dir: Path | None = None,
) -> Iterator[Path]:
    """Yield an intermediate PDF; remove temporary files on exit.

    This stage alone does not establish anonymity.
    """
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise ValueError("Input must be a regular file.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive.")

    gs = find_ghostscript(executable)
    with TemporaryDirectory(prefix="pdfblinder-", dir=work_dir) as directory:
        output = Path(directory) / "reconstructed.pdf"
        command = [
            gs,
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-dPDFSTOPONERROR",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            "-dAutoRotatePages=/None",
            "-dToUnicodeForStdEnc=true",
            "-sUseOCR=Never",
            "-dPreserveAnnots=false",
            "-dShowAnnots=false",
            "-dPreserveMarkedContent=true",
            "-dDownsampleColorImages=false",
            "-dDownsampleGrayImages=false",
            "-dDownsampleMonoImages=false",
            f"-sOutputFile={output}",
            "-f",
            str(source),
        ]
        try:
            environment = os.environ.copy()
            environment.pop("GS_OPTIONS", None)
            for variable in ("TMPDIR", "TEMP", "TMP"):
                environment[variable] = directory
            with (Path(directory) / "renderer.log").open("wb") as log:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                    env=environment,
                )
        except subprocess.TimeoutExpired as exc:
            raise GhostscriptError(f"Ghostscript exceeded the {timeout:g}-second timeout.") from exc
        except OSError as exc:
            raise GhostscriptError(f"Could not execute Ghostscript: {exc}") from exc

        if result.returncode != 0:
            raise GhostscriptError(
                f"Ghostscript rejected input (exit code {result.returncode}); "
                "renderer diagnostics are withheld to protect document content."
            )
        # PDFSTOPONWARNING breaks ToUnicode with some GS versions. Instead,
        # reject logged warnings after a completed reconstruction; the bounded
        # worker log stays private and is covered by disk/time limits.
        with (Path(directory) / "renderer.log").open("rb") as log:
            while block := log.read(65536):
                if b"warning" in block.lower():
                    raise GhostscriptError(
                        "Ghostscript reported warnings; re-export or investigate the input."
                    )
        if not output.is_file() or output.stat().st_size == 0:
            raise GhostscriptError("Ghostscript produced no PDF output.")

        yield output
