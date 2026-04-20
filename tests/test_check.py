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


# ---------------------------------------------------------------------------
# Issue 09 — --workers accepts "auto" and rejects invalid values
# ---------------------------------------------------------------------------


def test_workers_auto_accepted(runner, tla_file):
    """--workers auto must be accepted without a click error."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--workers", "auto"])
    assert result.exit_code == 0


def test_workers_integer_accepted(runner, tla_file):
    """--workers 2 must still work after replacing the type."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--workers", "2"])
    assert result.exit_code == 0


def test_workers_zero_rejected(runner, tla_file):
    """--workers 0 must fail with a message mentioning 'positive'."""
    result = runner.invoke(cli, ["model-check", str(tla_file), "--workers", "0"])
    assert result.exit_code != 0
    assert "positive" in result.output.lower()


def test_workers_invalid_string_rejected(runner, tla_file):
    """--workers foo must fail."""
    result = runner.invoke(cli, ["model-check", str(tla_file), "--workers", "foo"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Issue 14 — --no-deadlock, --continue, --difftrace are accepted
# ---------------------------------------------------------------------------


def test_no_deadlock_flag_accepted(runner, tla_file):
    """--no-deadlock must be accepted and not raise an error."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--no-deadlock"])
    assert result.exit_code == 0


def test_continue_flag_accepted(runner, tla_file):
    """--continue must be accepted and not raise an error."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--continue"])
    assert result.exit_code == 0


def test_difftrace_flag_accepted(runner, tla_file):
    """--difftrace must be accepted and not raise an error."""
    with patch("tla_cli.wrappers.tlc.TLC.start", return_value=_make_run(True)):
        result = runner.invoke(cli, ["model-check", str(tla_file), "--difftrace"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Issue 14 — flag propagation: new flags are forwarded to TLC.start
# ---------------------------------------------------------------------------


def test_no_deadlock_passed_to_tlc(runner, tla_file):
    """TLC.start must receive no_deadlock=True when --no-deadlock is given."""
    with patch("tla_cli.wrappers.tlc.TLC.start") as mock_start:
        mock_start.return_value = _make_run(True)
        runner.invoke(cli, ["model-check", str(tla_file), "--no-deadlock"])
    _, kwargs = mock_start.call_args
    assert kwargs.get("no_deadlock") is True


def test_continue_passed_to_tlc(runner, tla_file):
    """TLC.start must receive continue_after_error=True when --continue is given."""
    with patch("tla_cli.wrappers.tlc.TLC.start") as mock_start:
        mock_start.return_value = _make_run(True)
        runner.invoke(cli, ["model-check", str(tla_file), "--continue"])
    _, kwargs = mock_start.call_args
    assert kwargs.get("continue_after_error") is True


def test_difftrace_passed_to_tlc(runner, tla_file):
    """TLC.start must receive difftrace=True when --difftrace is given."""
    with patch("tla_cli.wrappers.tlc.TLC.start") as mock_start:
        mock_start.return_value = _make_run(True)
        runner.invoke(cli, ["model-check", str(tla_file), "--difftrace"])
    _, kwargs = mock_start.call_args
    assert kwargs.get("difftrace") is True


def test_workers_auto_passed_to_tlc(runner, tla_file):
    """TLC.start must receive workers='auto' when --workers auto is given."""
    with patch("tla_cli.wrappers.tlc.TLC.start") as mock_start:
        mock_start.return_value = _make_run(True)
        runner.invoke(cli, ["model-check", str(tla_file), "--workers", "auto"])
    _, kwargs = mock_start.call_args
    assert kwargs.get("workers") == "auto"
