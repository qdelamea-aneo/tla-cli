"""Functional (integration) tests for the tla parse command.

These tests launch real SANY processes against specs in tests/specs/.
They are slow and require tla2tools.jar to be present.

Run with:
    uv run pytest tests/test_parse_functional.py -v

Skip via the 'integration' mark:
    uv run pytest -m "not integration"
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tla_cli.cli import cli

SPECS = Path(__file__).parent / "specs"

pytestmark = pytest.mark.integration


@pytest.fixture()
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# text mode exit codes
# ---------------------------------------------------------------------------


def test_parse_exits_0_on_clean_spec(runner):
    """Counter.tla is syntactically and semantically valid → exit 0."""
    result = runner.invoke(cli, ["parse", str(SPECS / "Counter.tla"), "--no-progress"])
    assert result.exit_code == 0, result.output


def test_parse_exits_1_on_semantic_error(runner):
    """SemanticError.tla uses an undeclared operator → SANY reports *** Errors: 1.
    Even though SANY exits 0, the CLI must exit 1."""
    result = runner.invoke(cli, ["parse", str(SPECS / "SemanticError.tla"), "--no-progress"])
    assert result.exit_code == 1, result.output


def test_parse_shows_error_message_for_semantic_error(runner):
    """The error panel must mention the unknown operator, not 'Parsed successfully'."""
    result = runner.invoke(cli, ["parse", str(SPECS / "SemanticError.tla"), "--no-progress"])
    assert "undeclaredVar" in result.output or "Unknown operator" in result.output
    assert "successfully" not in result.output


def test_parse_exits_1_on_syntax_error(runner):
    """SyntaxError.tla has a malformed expression → SANY parse exception → exit 1."""
    result = runner.invoke(cli, ["parse", str(SPECS / "SyntaxError.tla"), "--no-progress"])
    assert result.exit_code == 1, result.output


# ---------------------------------------------------------------------------
# JSON mode exit codes
# ---------------------------------------------------------------------------


def test_parse_json_exits_0_on_clean_spec(runner):
    result = runner.invoke(
        cli, ["parse", str(SPECS / "Counter.tla"), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["success"] is True


def test_parse_json_exits_1_on_semantic_error(runner):
    result = runner.invoke(
        cli, ["parse", str(SPECS / "SemanticError.tla"), "--format", "json"]
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["success"] is False


def test_parse_json_includes_errors_on_semantic_failure(runner):
    """The JSON payload must include the error diagnostics."""
    result = runner.invoke(
        cli, ["parse", str(SPECS / "SemanticError.tla"), "--format", "json"]
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert len(data["errors"]) > 0
    combined = " ".join(e["message"] for e in data["errors"])
    assert "undeclaredVar" in combined or "Unknown operator" in combined
