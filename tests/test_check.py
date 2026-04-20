"""Unit tests for the model-check and simulate CLI commands.

The TLC subprocess calls are mocked by patching TLC.start / TLC.simulate at
the class level so that the real CLI group wiring is exercised (context setup,
option parsing, the error_handler decorator) while no actual Java process is
spawned.

Key assertions: the commands must propagate run.success to the process exit
code in both text and JSON output modes.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tla_cli.cli import cli
from tla_cli.wrappers.tlc import TLCRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(success: bool | None) -> TLCRun:
    run = TLCRun(started_at=datetime.now())
    run.success = success
    if success is False:
        run.error_kind = "safety_violation"
        run.error_type = "Safety failure"
    return run


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def tla_file(tmp_path) -> Path:
    """Minimal .tla file that satisfies Click's exists=True check."""
    f = tmp_path / "Spec.tla"
    f.write_text("---- MODULE Spec ----\n====\n")
    return f


# ---------------------------------------------------------------------------
# model-check — text mode
# ---------------------------------------------------------------------------


def test_model_check_exits_0_on_success(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file)])
    assert result.exit_code == 0


def test_model_check_exits_1_on_failure(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(False)):
        result = runner.invoke(cli, ["model-check", str(tla_file)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# model-check — JSON mode
# ---------------------------------------------------------------------------


def test_model_check_json_exits_0_on_success(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True


def test_model_check_json_exits_1_on_failure(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(False)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["success"] is False


def test_model_check_json_output_written_before_nonzero_exit(runner, tla_file):
    """JSON payload must be written to stdout even when the exit code is 1."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(False)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "success" in data


# ---------------------------------------------------------------------------
# simulate — text mode
# ---------------------------------------------------------------------------


def test_simulate_exits_0_on_success(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(True)):
        result = runner.invoke(cli, ["simulate", str(tla_file)])
    assert result.exit_code == 0


def test_simulate_exits_1_on_failure(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(False)):
        result = runner.invoke(cli, ["simulate", str(tla_file)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# simulate — JSON mode
# ---------------------------------------------------------------------------


def test_simulate_json_exits_0_on_success(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(True)):
        result = runner.invoke(cli, ["simulate", str(tla_file), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True


def test_simulate_json_exits_1_on_failure(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(False)):
        result = runner.invoke(cli, ["simulate", str(tla_file), "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["success"] is False


def test_simulate_json_output_written_before_nonzero_exit(runner, tla_file):
    """JSON payload must be present even when exit code is 1."""
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(False)):
        result = runner.invoke(cli, ["simulate", str(tla_file), "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "success" in data


# ---------------------------------------------------------------------------
# success=None edge case (TLC killed / timed out before producing output)
# ---------------------------------------------------------------------------


def test_model_check_exits_1_when_success_is_none(runner, tla_file):
    """`not None` is truthy, so success=None must also yield exit 1."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(None)):
        result = runner.invoke(cli, ["model-check", str(tla_file)])
    assert result.exit_code == 1


def test_simulate_exits_1_when_success_is_none(runner, tla_file):
    with patch("tla_cli.wrappers.tlc.TLC.simulate", return_value=_make_run(None)):
        result = runner.invoke(cli, ["simulate", str(tla_file)])
    assert result.exit_code == 1
