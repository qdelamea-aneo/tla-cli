"""Unit tests for the proof-check CLI command.

Uses Click's CliRunner to exercise option parsing and input validation
without launching a real tlapm process.
"""

import pytest

from click.testing import CliRunner
from pathlib import Path

from cli.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def tla_file(tmp_path) -> Path:
    """A minimal .tla file that exists on disk."""
    f = tmp_path / "Spec.tla"
    f.write_text("---- MODULE Spec ----\n====\n")
    return f


@pytest.fixture()
def jar_file(tmp_path) -> Path:
    """A .jar file that exists on disk."""
    f = tmp_path / "extra.jar"
    f.write_bytes(b"PK")  # minimal zip header
    return f


@pytest.fixture()
def module_dir(tmp_path) -> Path:
    """A directory that exists on disk."""
    d = tmp_path / "modules"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# JAR validation
# ---------------------------------------------------------------------------


def test_jar_file_rejected(runner, tla_file, jar_file):
    """Passing a .jar to --external-module must produce a clear error."""
    result = runner.invoke(
        cli,
        ["proof-check", str(tla_file), "--external-module", str(jar_file)],
    )
    assert result.exit_code != 0
    assert "JAR" in result.output
    assert jar_file.name in result.output


def test_jar_error_mentions_alternative(runner, tla_file, jar_file):
    """The error message must hint at the correct alternative."""
    result = runner.invoke(
        cli,
        ["proof-check", str(tla_file), "--external-module", str(jar_file)],
    )
    # Should mention .tla file or directory as the right thing to pass
    assert ".tla" in result.output or "directory" in result.output


# ---------------------------------------------------------------------------
# Valid inputs accepted (validation only — tlapm not invoked)
# ---------------------------------------------------------------------------


def test_tla_file_passes_validation(runner, tla_file):
    """.tla files must pass the JAR guard (the command may succeed or fail further
    down depending on whether tlapm is available, but the JAR error must not appear)."""
    result = runner.invoke(
        cli,
        ["proof-check", str(tla_file), "--external-module", str(tla_file)],
    )
    assert "JAR" not in result.output


def test_directory_passes_validation(runner, tla_file, module_dir):
    """Directories must pass the JAR guard (same caveat as tla_file test)."""
    result = runner.invoke(
        cli,
        ["proof-check", str(tla_file), "--external-module", str(module_dir)],
    )
    assert "JAR" not in result.output


def test_multiple_external_modules_first_jar_rejected(runner, tla_file, jar_file, module_dir):
    """The first JAR in a list of --external-module entries is rejected."""
    result = runner.invoke(
        cli,
        [
            "proof-check", str(tla_file),
            "--external-module", str(jar_file),
            "--external-module", str(module_dir),
        ],
    )
    assert result.exit_code != 0
    assert "JAR" in result.output
