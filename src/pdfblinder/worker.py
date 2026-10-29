"""Private worker entry point. Never called with an untrusted configuration."""

import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from .limits import Limits, linux_hard_limits


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def process_job(work, config):
    # Apply kernel limits before importing native parsers or opening the PDF.
    limits = Limits(**config["limits"])
    linux_hard_limits(limits, config["timeout"])
    import pikepdf
    import pypdfium2

    from .core import InputError
    from .ghostscript import find_ghostscript, reconstructed_pdf
    from .independent import verify_independently
    from .inspection import compare_documents, inspect_input
    from .limits import LimitError
    from .raster import build_raster
    from .sanitize import sanitize_intermediate
    from .verify import verify_pdf

    source, candidate = work / "input.pdf", work / "candidate.pdf"
    profile = config["profile"]
    gs = find_ghostscript(config["executable"])
    gs_version = (
        subprocess.run([gs, "--version"], capture_output=True, timeout=5, check=True)
        .stdout.decode()
        .strip()
    )
    with pikepdf.Pdf.open(source, attempt_recovery=False) as original:
        if original.is_encrypted:
            raise InputError("Encrypted input PDFs are not supported.")
        page_count = len(original.pages)
        if not page_count:
            raise InputError("Input PDF contains no pages.")
        if page_count > limits.max_pages or len(original.objects) > limits.max_objects:
            raise LimitError("Page or PDF object limit exceeded.")
        if "/AcroForm" in original.Root:
            raise InputError(
                "PDFs with forms or signature fields are not supported; export a static copy."
            )
        if "/OCProperties" in original.Root:
            raise InputError("Optional-content layers require manual investigation and re-export.")
        for page in original.pages:
            if float(page.obj.get("/UserUnit", 1)) != 1:
                raise InputError(
                    "Nonstandard page UserUnit is not supported by independent validation."
                )
            box = list(page.mediabox)
            if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
                raise InputError("Invalid page geometry.")
        if profile == "vector":

            def alternate_requires_review(properties):
                if not isinstance(properties, pikepdf.Dictionary):
                    return False
                if set(properties.keys()) & {"/Alt", "/E", "/OC"}:
                    return True
                # Browser exports legitimately use ActualText for fi/fl glyphs.
                # Allow only this fixed typographic vocabulary; arbitrary text
                # still fails. NFKC extraction equality is checked after removal.
                ligatures = {"fi", "fl", "ff", "ffi", "ffl", "st"}
                return (
                    "/ActualText" in properties and str(properties["/ActualText"]) not in ligatures
                )

            # Alternate text can carry strings a visual inspection never sees.
            # Inspect actual drawing/property operands, including nested forms.
            pending = list(original.pages)
            seen_streams = set()
            while pending:
                drawing = pending.pop()
                stream = drawing.obj if isinstance(drawing, pikepdf.Page) else drawing
                identity = stream.objgen
                if identity in seen_streams:
                    continue
                seen_streams.add(identity)
                instructions = pikepdf.parse_content_stream(drawing, operators="BDC DP")
                for instruction in instructions:
                    for operand in instruction.operands:
                        if alternate_requires_review(operand):
                            raise InputError(
                                "Alternate or optional-content text requires manual investigation."
                            )
                resources = stream.get("/Resources", pikepdf.Dictionary())
                for properties in resources.get("/Properties", pikepdf.Dictionary()).values():
                    if alternate_requires_review(properties):
                        raise InputError("Alternate-text properties require manual investigation.")
                pending.extend(
                    item
                    for item in resources.get("/XObject", pikepdf.Dictionary()).values()
                    if isinstance(item, pikepdf.Stream)
                    and item.get("/Subtype") == pikepdf.Name("/Form")
                )
        # PDF CMap mapping blocks are limited to 100 entries. Older GS
        # versions can silently accept oversized blocks; enforce this here.
        for obj in original.objects:
            if not isinstance(obj, pikepdf.Dictionary) or obj.get("/Type") != pikepdf.Name("/Font"):
                continue
            if "/ToUnicode" not in obj:
                continue
            mapping = obj["/ToUnicode"]
            if not isinstance(mapping, pikepdf.Stream):
                raise InputError("Invalid ToUnicode CMap object.")
            data = mapping.read_bytes()
            if len(data) > min(16 * 1024 * 1024, limits.max_work_bytes):
                raise LimitError("Decoded ToUnicode CMap size limit exceeded.")
            data = re.sub(rb"%[^\r\n]*", b"", data)
            for count in re.findall(
                rb"(?<![\w.])(-?\d+)\s+begin(?:bfchar|bfrange|codespacerange)\b", data
            ):
                if not 0 <= int(count) <= 100:
                    raise InputError("Malformed ToUnicode CMap block count; re-export the source.")
        identifiers = tuple(bytes(item) for item in original.trailer.get("/ID", []))
        annotations = sum(len(page.obj.get("/Annots", [])) for page in original.pages)
        issues = original.check_pdf_syntax() + original.get_warnings()
        if issues:
            raise InputError("Input PDF has structural warnings; repair/re-export it first.")
    _, dimensions = inspect_input(source, limits, profile=profile)
    if profile == "vector":
        with reconstructed_pdf(
            source, executable=gs, timeout=config["timeout"], work_dir=work
        ) as intermediate:
            with candidate.open("xb") as output:
                sanitize_intermediate(intermediate, output)
    else:
        build_raster(source, candidate, limits, dpi=config["dpi"])
    verify_pdf(candidate, expected_pages=page_count, original_ids=identifiers)
    independent = verify_independently(
        candidate, limits, expected_pages=page_count, profile=profile
    )
    comparison_dpi = config["dpi"] if profile == "raster" else 144
    comparisons = compare_documents(source, candidate, limits, profile=profile, dpi=comparison_dpi)
    report = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "created_utc": datetime.now(UTC).isoformat(),
        "tool": "PDFblinder",
        "tool_version": version("pdfblinder"),
        "code_sha256": hashlib.sha256(
            b"".join(
                item.name.encode() + b"\0" + item.read_bytes()
                for item in sorted(Path(__file__).parent.glob("*.py"))
            )
        ).hexdigest(),
        "policy": f"journal-{profile}-v1",
        "profile": profile,
        "input_sha256": sha256(source),
        "output_sha256": sha256(candidate),
        "pages": page_count,
        "page_dimensions_points": dimensions,
        "annotations_discarded": annotations,
        "limits": asdict(limits),
        "whole_job_timeout_seconds": config["timeout"],
        "resource_enforcement": "sampled-process-tree-and-disk; Linux inherited rlimits when available",
        "runtime": {
            "python": platform.python_version(),
            "os": platform.system(),
            "ghostscript": gs_version,
            "pdfium": str(pypdfium2.PDFIUM_INFO),
            **{
                name: version(name)
                for name in ["pikepdf", "pypdf", "pypdfium2", "Pillow", "psutil"]
            },
        },
        "checks": {
            "qpdf_structure": "passed",
            "independent_structure": independent,
            "render_comparison": comparisons,
            "render_comparison_dpi": comparison_dpi,
            "hidden_text_screening": "passed-known-detectors"
            if profile == "vector"
            else "source-objects-not-copied",
        },
        "technical_status": "passed",
        "human_review": "pending",
        "approved_for_submission": False,
        "limitations": [
            "Visible identifying content requires human review.",
            "Vector visibility screening is not an exhaustive proof of no hidden content.",
            "No guarantee against steganography or authorship fingerprinting.",
            "Audit hashes link to the source; keep this report private.",
        ],
    }
    (work / "audit.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    work = Path(sys.argv[1]).resolve().parent
    try:
        config = json.loads((work / "config.json").read_text())
        process_job(work, config)
        result = {"status": "passed"}
        code = 0
    except BaseException as exc:
        # Never echo manuscript data or renderer diagnostics into public logs.
        safe = type(exc).__name__ in {
            "InputError",
            "LimitError",
            "InspectionError",
            "VerificationError",
            "SanitationError",
            "GhostscriptError",
        }
        message = (
            str(exc)
            if safe
            else f"PDF processing failed ({type(exc).__name__}); input retained, no output published."
        )
        result = {"status": "rejected", "error_type": type(exc).__name__, "message": message[:2000]}
        code = 1
    (work / "result.json").write_text(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
