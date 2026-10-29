import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "pdfblinder", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("entrypoint", ["module", "console"])
def test_cli_success_and_overwrite_protection(tmp_path, entrypoint):
    source = tmp_path / "input with spaces.pdf"
    output = tmp_path / "output with spaces.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.docinfo["/Author"] = "Private Author"
        pdf.save(source)
    original_bytes = source.read_bytes()

    if entrypoint == "module":
        command = [sys.executable, "-m", "pdfblinder"]
    else:
        executable = str(
            Path(sys.executable).with_name(
                "pdfblinder.exe" if sys.platform == "win32" else "pdfblinder"
            )
        )
        assert executable is not None
        command = [executable]

    result = subprocess.run(
        [*command, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Structural verification passed" in result.stdout
    assert output.is_file()
    assert source.read_bytes() == original_bytes
    with pikepdf.Pdf.open(output) as pdf:
        assert len(pdf.pages) == 1
        assert "/Info" not in pdf.trailer

    output_bytes = output.read_bytes()
    repeated = subprocess.run(
        [*command, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert repeated.returncode == 1
    assert "already exists" in repeated.stderr
    assert "Traceback" not in repeated.stderr
    assert output.read_bytes() == output_bytes


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "abc"])
def test_cli_rejects_invalid_timeout(tmp_path, timeout):
    output = tmp_path / "output.pdf"
    result = run_cli("--timeout", timeout, tmp_path / "input.pdf", output)
    assert result.returncode == 2
    assert "Timeout must" in result.stderr
    assert not output.exists()


def test_cli_missing_input(tmp_path):
    output = tmp_path / "output.pdf"
    result = run_cli(tmp_path / "missing.pdf", output)
    assert result.returncode == 1
    assert "pdfblinder: error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_cli_invalid_pdf(tmp_path):
    source = tmp_path / "invalid.pdf"
    source.write_bytes(b"This is not a PDF.")
    output = tmp_path / "output.pdf"
    result = run_cli(source, output)
    assert result.returncode == 1
    assert "pdfblinder: error:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_cli_version():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "pdfblinder 0.2.0.dev0"
