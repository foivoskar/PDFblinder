"""Supervise the entire parsing/rendering job in a separate process."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import psutil

from .limits import LimitError, Limits, validate_timeout


class InputError(ValueError):
    """Unsupported input or job options."""


class ProcessingError(RuntimeError):
    """An isolated worker rejected or failed the job."""


def _kill_tree(process):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
        children = []
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def _work_size(directory):
    size = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            pass  # renderer cleanup can race this sample
    return size


def _supervise(config_path, work, limits, deadline):
    # Document-controlled settings cannot override the fixed GS command line.
    env = os.environ.copy()
    env.pop("GS_OPTIONS", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "pdfblinder.worker", str(config_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=(os.name == "posix"),
    )
    try:
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise LimitError("Whole-job time limit exceeded; no output published.")
            try:
                parent = psutil.Process(process.pid)
                processes = [parent, *parent.children(recursive=True)]
                memory = 0
                for child in processes:
                    try:
                        memory += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                if memory > limits.max_memory_bytes:
                    raise LimitError("Process-tree memory limit exceeded.")
            except psutil.NoSuchProcess:
                pass
            except (psutil.AccessDenied, PermissionError) as exc:
                raise LimitError("OS denied process-resource monitoring; job stopped.") from exc
            if _work_size(work) > limits.max_work_bytes:
                raise LimitError("Temporary disk limit exceeded.")
            time.sleep(0.05)
        if time.monotonic() > deadline:
            raise LimitError("Whole-job time limit exceeded.")
        if _work_size(work) > limits.max_work_bytes:
            raise LimitError("Temporary disk limit exceeded.")
        result_path = work / "result.json"
        if not result_path.is_file() or result_path.stat().st_size > 1024 * 1024:
            raise ProcessingError(
                "Worker terminated without a valid result (possibly an OS resource limit)."
            )
        result = json.loads(result_path.read_text())
        if process.returncode or result.get("status") != "passed":
            from .ghostscript import GhostscriptError
            from .sanitize import SanitationError
            from .verify import VerificationError

            errors = {
                "InputError": InputError,
                "LimitError": LimitError,
                "GhostscriptError": GhostscriptError,
                "SanitationError": SanitationError,
                "VerificationError": VerificationError,
            }
            error = errors.get(result.get("error_type"), ProcessingError)
            raise error(result.get("message", "Worker rejected input."))
    finally:
        # Also clean up a descendant if its parent exited unexpectedly.
        _kill_tree(process)


def _publish(source, destination):
    """No-clobber atomic publication on filesystems with hard-link support."""
    descriptor, name = tempfile.mkstemp(prefix=".pdfblinder-", dir=destination.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        # Never fall back to overwrite/partial-copy behavior on unsupported FS.
        os.link(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def blind_pdf(
    source: Path,
    destination: Path,
    *,
    executable=None,
    timeout=120,
    profile="vector",
    report=None,
    limits=None,
    dpi=300,
) -> int:
    """Create verified PDF + private audit; human approval is always pending."""
    validate_timeout(timeout)
    limits = limits or Limits()
    if profile not in {"vector", "raster"}:
        raise InputError("Profile must be vector or raster.")
    if not isinstance(dpi, int) or isinstance(dpi, bool) or not 144 <= dpi <= 600:
        raise InputError("Raster DPI must be an integer between 144 and 600.")
    deadline = time.monotonic() + timeout
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().absolute()
    report = (
        Path(report).expanduser().absolute() if report else Path(str(destination) + ".audit.json")
    )
    if not source.is_file():
        raise InputError("Input must be a regular file.")
    for path in (destination, report):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Output already exists: {path}")
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Output directory does not exist: {path.parent}")
    if destination.parent.resolve() / destination.name == report.parent.resolve() / report.name:
        raise InputError("PDF and audit report paths must differ.")
    if source.stat().st_size > limits.max_input_bytes:
        raise LimitError("Input file exceeds size limit.")
    with tempfile.TemporaryDirectory(prefix="pdfblinder-job-") as directory:
        work = Path(directory)
        snapshot = work / "input.pdf"
        # Bound the copy too: a growing file must not bypass the initial stat.
        with source.open("rb") as input_stream, snapshot.open("xb") as output:
            copied = 0
            while chunk := input_stream.read(1024 * 1024):
                copied += len(chunk)
                if copied > limits.max_input_bytes or copied > limits.max_work_bytes:
                    raise LimitError("Input copy exceeds job size limit.")
                if time.monotonic() > deadline:
                    raise LimitError("Whole-job time limit exceeded while copying input.")
                output.write(chunk)
        config = {
            "limits": asdict(limits),
            "timeout": max(0.01, deadline - time.monotonic()),
            "profile": profile,
            "dpi": dpi,
            "executable": executable,
        }
        config_path = work / "config.json"
        config_path.write_text(json.dumps(config))
        _supervise(config_path, work, limits, deadline)
        audit = work / "audit.json"
        data = json.loads(audit.read_text())
        _publish(audit, report)
        try:
            _publish(work / "candidate.pdf", destination)
        except BaseException:
            report.unlink(missing_ok=True)
            raise
        return data["pages"]
