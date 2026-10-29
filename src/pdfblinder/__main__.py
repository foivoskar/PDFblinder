"""Command-line entry point for PDFblinder."""

import argparse
import math
from importlib.metadata import version
from pathlib import Path

import pikepdf

from .core import InputError, ProcessingError, blind_pdf
from .ghostscript import GhostscriptError
from .limits import LimitError, Limits
from .sanitize import SanitationError
from .verify import VerificationError


def positive_timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Timeout must be a positive number of seconds.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout must be finite and greater than zero.")
    return seconds


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pdfblinder",
        description="Sanitize a review PDF with independent checks and a private audit.",
        epilog=(
            "Annotations are discarded. Forms and encrypted PDFs are "
            "rejected. Identifying visible content and embedded font/image "
            "payloads are not exhaustively anonymized. Vector checks reject known "
            "hidden-text mechanisms. Human review is always required. The audit "
            "report contains linking hashes and must remain private."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('pdfblinder')}",
    )
    parser.add_argument("input", type=Path, help="Source PDF")
    parser.add_argument(
        "output",
        type=Path,
        help="Destination PDF; must not already exist",
    )
    parser.add_argument(
        "--gs",
        metavar="EXECUTABLE",
        help="Ghostscript executable name or path",
    )
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=120.0,
        metavar="SECONDS",
        help="Whole-job time limit in seconds (default: 120)",
    )
    parser.add_argument(
        "--profile",
        choices=["vector", "raster"],
        default="vector",
        help="vector preserves text (default); raster loses text/vector quality",
    )
    parser.add_argument(
        "--report", type=Path, help="Private audit path (default: OUTPUT.audit.json)"
    )
    parser.add_argument(
        "--dpi", type=int, default=300, help="Raster resolution, 144-600 (default: 300)"
    )
    parser.add_argument("--max-input-mb", type=int, default=100)
    parser.add_argument("--max-work-mb", type=int, default=512)
    parser.add_argument("--max-memory-mb", type=int, default=1536)
    parser.add_argument("--max-pages", type=int, default=200)
    args = parser.parse_args()

    try:
        pages = blind_pdf(
            args.input,
            args.output,
            executable=args.gs,
            timeout=args.timeout,
            profile=args.profile,
            report=args.report,
            dpi=args.dpi,
            limits=Limits(
                max_input_bytes=args.max_input_mb * 1024 * 1024,
                max_work_bytes=args.max_work_mb * 1024 * 1024,
                max_memory_bytes=args.max_memory_mb * 1024 * 1024,
                max_pages=args.max_pages,
            ),
        )
    except (
        OSError,
        ValueError,
        ProcessingError,
        LimitError,
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
    print("Structural verification passed; independent checks passed.")
    print("Human review: PENDING. Not approved for submission automatically.")
    print(f"Private audit: {args.report or str(args.output) + '.audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
