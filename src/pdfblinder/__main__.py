"""Command-line entry point for PDFblinder."""

import argparse
from importlib.metadata import version
import math
from pathlib import Path

import pikepdf

from .core import InputError, blind_pdf
from .ghostscript import GhostscriptError
from .sanitize import SanitationError
from .verify import VerificationError


def positive_timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Timeout must be a positive number of seconds."
        ) from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(
            "Timeout must be finite and greater than zero."
        )
    return seconds


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pdfblinder",
        description="Reconstruct and structurally sanitize a PDF.",
        epilog=(
            "Annotations are discarded. Forms and encrypted PDFs are "
            "rejected. Identifying visible content and embedded font/image "
            "payloads are not anonymized. Review the output before submission."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('pdfblinder')}",
    )
    parser.add_argument("input", type=Path, help="Source PDF")
    parser.add_argument(
        "output", type=Path,
        help="Destination PDF; must not already exist",
    )
    parser.add_argument(
        "--gs", metavar="EXECUTABLE",
        help="Ghostscript executable name or path",
    )
    parser.add_argument(
        "--timeout", type=positive_timeout, default=120.0,
        metavar="SECONDS",
        help="Ghostscript time limit in seconds (default: 120)",
    )
    args = parser.parse_args()

    try:
        pages = blind_pdf(
            args.input,
            args.output,
            executable=args.gs,
            timeout=args.timeout,
        )
    except (
        OSError,
        pikepdf.PdfError,
        InputError,
        GhostscriptError,
        SanitationError,
        VerificationError,
    ) as exc:
        parser.exit(1, f"pdfblinder: error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "pdfblinder: interrupted\n")

    print(f"Created: {args.output} ({pages} pages)")
    print("Structural verification passed. Review the output before submission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
