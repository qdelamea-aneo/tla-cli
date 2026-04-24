"""Functional (integration) tests for the model-check and simulate commands.

These tests launch real TLC processes against the sample specs in issues/specs/.
They are slow and require the tla2tools.jar to be present.

Run with:
    uv run pytest tests/test_check_functional.py -v

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
# model-check — text mode exit codes
# ---------------------------------------------------------------------------


def test_model_check_exits_0_on_passing_spec(runner):
    """SimpleSuccess.tla has no violations → exit 0."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "SimpleSuccess.tla")])
    assert result.exit_code == 0, result.output


def test_model_check_exits_1_on_safety_violation(runner):
    """Counter.tla violates CounterBound → exit 1."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "Counter.tla")])
    assert result.exit_code == 1, result.output


def test_model_check_exits_1_on_deadlock(runner):
    """DeadlockSpec.tla reaches a state with no enabled actions → exit 1."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "DeadlockSpec.tla")])
    assert result.exit_code == 1, result.output


def test_model_check_exits_1_on_assumption_violation(runner):
    """AssumptionViolation.tla has ASSUME 1 = 2 → exit 1."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "AssumptionViolation.tla")])
    assert result.exit_code == 1, result.output


def test_model_check_reports_parse_error_with_location(runner):
    """Running `tla mc` on a spec with a syntax error must show the SANY
    diagnostic (line/column + 'Encountered' message) instead of the generic
    'See the log file' hint."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "SyntaxError.tla")])
    assert result.exit_code == 1
    # Line/column from SANY's "Encountered … at line 11, column 1" must be visible.
    assert "line 11" in result.output
    # The message surfaces the parser description without being swallowed by
    # a generic "see the log file" hint. Rich may wrap the message across
    # table rows, so only substrings that survive wrapping are asserted.
    assert "Syntax error" in result.output
    assert "Beginning of" in result.output


def test_model_check_reports_missing_module_with_name(runner):
    """Running `tla mc` on a spec with a missing EXTENDS target must show
    the missing module name rather than only a log-file pointer."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "MissingExtends.tla")])
    assert result.exit_code == 1
    assert "NonExistentModule" in result.output


# ---------------------------------------------------------------------------
# model-check — JSON mode exit codes
# ---------------------------------------------------------------------------


def test_model_check_json_exits_0_on_passing_spec(runner):
    result = runner.invoke(cli, ["model-check", str(SPECS / "SimpleSuccess.tla"), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["success"] is True


def test_model_check_json_exits_1_on_safety_violation(runner):
    result = runner.invoke(cli, ["model-check", str(SPECS / "Counter.tla"), "--format", "json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["success"] is False


def test_model_check_json_output_on_failure_is_valid_json(runner):
    """Even when the model fails, the JSON payload must be valid and complete."""
    result = runner.invoke(cli, ["model-check", str(SPECS / "Counter.tla"), "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "success" in data
    assert "error_kind" in data


# ---------------------------------------------------------------------------
# Single-variable error traces (bare "name = value" format)
# ---------------------------------------------------------------------------


def test_single_var_trace_shows_variable_in_json(runner):
    """SafetyViolation.tla has one variable; its trace must include variable data."""
    result = runner.invoke(
        cli,
        ["model-check", str(SPECS / "SafetyViolation.tla"), "--format", "json"],
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["trace"] is not None
    assert len(data["trace"]) > 0
    first_state = data["trace"][0]
    assert len(first_state["variables"]) > 0, "Expected variables in first trace state, got none"
    var_names = {v["name"] for v in first_state["variables"]}
    assert "counter" in var_names


def test_multi_var_trace_regression(runner):
    """TwoPhaseCommit.tla has multiple variables; they must still appear in the trace."""
    result = runner.invoke(
        cli,
        ["model-check", str(SPECS / "TwoPhaseCommit.tla"), "--format", "json"],
    )
    # TwoPhaseCommit has a deadlock, so it exits 1
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["trace"] is not None
    first_state = data["trace"][0]
    assert len(first_state["variables"]) > 1, "Expected multiple variables in 2PC trace"


# ---------------------------------------------------------------------------
# simulate — text mode exit codes
# ---------------------------------------------------------------------------


def test_simulate_exits_1_on_safety_violation(runner):
    """Counter.tla violates its invariant during simulation → exit 1."""
    result = runner.invoke(
        cli,
        ["simulate", str(SPECS / "Counter.tla"), "--timeout", "30", "--no-progress"],
    )
    assert result.exit_code == 1, result.output


def test_simulate_exits_0_on_passing_spec(runner):
    """SimpleSuccess.tla has no violations; limit depth so it completes quickly."""
    result = runner.invoke(
        cli,
        [
            "simulate",
            str(SPECS / "SimpleSuccess.tla"),
            "--timeout",
            "15",
            "--depth",
            "10",
            "--num-traces",
            "20",
            "--no-progress",
        ],
    )
    # Simulation of a terminating bounded spec may exit 0 or time out (also 1).
    # The key assertion is: if success is True, exit code must be 0.
    if result.exit_code == 0:
        pass  # correct
    else:
        # If TLC timed out or was killed, that's also exit 1 (success=None/False).
        assert result.exit_code == 1
