"""Unit tests for the TLC output parser.

All tests are pure unit tests — no TLC process is launched.  Synthetic TLC
output strings that mirror real TLC log output are fed to
:class:`~cli.tools.tlc_output.TLCOutputParser` line-by-line, and the
resulting parser state is verified.
"""

import pytest

from datetime import datetime

from tla_cli.tools.tlc_output import (
    TLCActionCoverage,
    TLCDiagnostic,
    TLCOutputParser,
    TLCPhase,
    TLCProgress,
    TLCStateVariable,
    TLCTraceState,
)
from tla_cli.tools.tlc import TLCRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(output: str) -> TLCOutputParser:
    """Feed a multi-line TLC output string to a fresh parser and return it."""
    parser = TLCOutputParser()
    for line in output.splitlines():
        parser.feed_line(line)
    return parser


def populated_run(output: str) -> TLCRun:
    """Parse *output* and return a :class:`TLCRun` populated via the parser."""
    parser = parse(output)
    run = TLCRun(started_at=datetime.now())
    parser.populate_run(run)
    return run


# ---------------------------------------------------------------------------
# Fixtures — shared TLC output snippets
# ---------------------------------------------------------------------------

HEADER = """\
TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)
Running breadth-first search Model-Checking with fp 23 and seed 9876 with 2 workers on 8 cores with 4096MB heap and 64MB offheap memory
Parsing file /specs/Foo.tla
Parsing file /specs/Bar.tla
"""

PROGRESS_LINE = (
    "Progress(5) at 2024-01-01 12:00:01: "
    "100 states generated (50 s/min), 42 distinct states found, "
    "10 states left on queue."
)

SUCCESS_TAIL = """\
Model checking completed. No error has been found.
3157 states generated, 512 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 7.
Finished in 2s at (2024-01-01 12:00:03)
"""

COVERAGE_BLOCK = """\
Coverage at 2024-01-01 12:00:03:
  <"Init" line 10 col 3 of module Foo>: 3 states generated
  <"Next" line 20 col 3 of module Foo>: 300 states generated
"""

CONFIG_NOT_FOUND = """\
TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)
Running breadth-first search Model-Checking with fp 23 and seed 9876 with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory
Error: Failed to open the configuration file /specs/Foo.cfg:
The exception was a tlc2.tool.ConfigFileException
Finished in 0s at (2024-01-01 12:00:00)
"""

SEMANTIC_ERROR_WITH_DIAGS = """\
TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)
Running breadth-first search Model-Checking with fp 23 and seed 9876 with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory
Parsing file /specs/Foo.tla
line 15, col 5 to line 15, col 12 of module Foo

Unknown operator: Baad

line 30, col 5 to line 30, col 20 of module Foo

Wrong number of arguments given to operator Inc

Error: Parsing or semantic analysis failed.
Finished in 0s at (2024-01-01 12:00:00)
"""

SEMANTIC_ERROR_NO_DIAGS = """\
TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)
Running breadth-first search Model-Checking with fp 23 and seed 9876 with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory
Parsing file /specs/Foo.tla
Cannot find source file for module Missing imported in module Foo.
Error: Parsing or semantic analysis failed.
Finished in 0s at (2024-01-01 12:00:00)
"""

DEADLOCK = (
    "TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)\n"
    "Running breadth-first search Model-Checking with fp 23 and seed 9876"
    " with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory\n"
    "Parsing file /specs/Foo.tla\n"
    "Finished computing initial states: 1 distinct state generated at 2024-01-01 12:00:00.\n"
    "Progress(2) at 2024-01-01 12:00:01: 5 states generated (10 s/min),"
    " 3 distinct states found, 0 states left on queue.\n"
    "Error: Deadlock reached.\n"
    "Error: The behavior up to this point is:\n"
    "State 1: <Init line 10, col 3 to line 12, col 4 of module Foo>\n"
    "/\\ x = 0\n"
    "/\\ y = 1\n"
    "\n"
    "State 2: <Next line 20, col 3 to line 22, col 4 of module Foo>\n"
    "/\\ x = 1\n"
    "/\\ y = 0\n"
    "\n"
    "5 states generated, 3 distinct states found, 0 states left on queue.\n"
    "The depth of the complete state graph search is 2.\n"
    "Finished in 1s at (2024-01-01 12:00:01)\n"
)

SAFETY_VIOLATION = (
    "TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)\n"
    "Running breadth-first search Model-Checking with fp 23 and seed 9876"
    " with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory\n"
    "Parsing file /specs/Foo.tla\n"
    "Finished computing initial states: 1 distinct state generated at 2024-01-01 12:00:00.\n"
    "Error: Invariant Inv is violated.\n"
    "Error: The behavior up to this point is:\n"
    "State 1: <Init line 10, col 3 to line 12, col 4 of module Foo>\n"
    "/\\ counter = 0\n"
    "\n"
    "State 2: <Increment line 20, col 3 to line 22, col 4 of module Foo>\n"
    "/\\ counter = 100\n"
    "\n"
    "10 states generated, 5 distinct states found, 0 states left on queue.\n"
    "The depth of the complete state graph search is 2.\n"
    "Finished in 1s at (2024-01-01 12:00:01)\n"
)

LIVENESS_VIOLATION = (
    "TLC2 Version 2.20 of Day Month 20?? (rev: abc1234)\n"
    "Running breadth-first search Model-Checking with fp 23 and seed 9876"
    " with 1 worker on 8 cores with 4096MB heap and 64MB offheap memory\n"
    "Parsing file /specs/Foo.tla\n"
    "Finished computing initial states: 1 distinct state generated at 2024-01-01 12:00:00.\n"
    "Checking 3 branches of temporal properties\n"
    "Error: Temporal properties were violated.\n"
    "\n"
    "Error: The following behavior constitutes a counter-example:\n"
    "\n"
    "State 1: <Initial predicate>\n"
    "/\\ active = FALSE\n"
    "\n"
    "State 2: <Start line 15, col 3 to line 18, col 4 of module Foo>\n"
    "/\\ active = TRUE\n"
    "\n"
    "State 3: <Stop line 25, col 3 to line 28, col 4 of module Foo>\n"
    "/\\ active = FALSE\n"
    "\n"
    "Back to state 2: <Start line 15, col 3 to line 18, col 4 of module Foo>\n"
    "\n"
    "Finished checking temporal properties in 00s at 2024-01-01 12:00:02\n"
    "30 states generated, 10 distinct states found, 0 states left on queue.\n"
    "The depth of the complete state graph search is 3.\n"
    "Finished in 2s at (2024-01-01 12:00:02)\n"
)

MULTILINE_TRACE = (
    "Error: Deadlock reached.\n"
    "Error: The behavior up to this point is:\n"
    "State 1: <Init line 1, col 1 to line 5, col 1 of module Baz>\n"
    "/\\ mapping = [a |-> 1,\n"
    "              b |-> 2,\n"
    "              c |-> 3]\n"
    "/\\ flag = TRUE\n"
    "\n"
    "Finished in 0s at (2024-01-01 12:00:00)\n"
)

ACTION_WITH_ARGS = (
    "Error: Deadlock reached.\n"
    "Error: The behavior up to this point is:\n"
    "State 1: <ProcessTask({t, u}) line 40, col 5 to line 44, col 30 of module Worker>\n"
    '/\\ status = "running"\n'
    "\n"
    "Finished in 0s at (2024-01-01 12:00:00)\n"
)


# ---------------------------------------------------------------------------
# Tests — version & configuration extraction
# ---------------------------------------------------------------------------


def test_version_extracted():
    p = parse(HEADER)
    assert p._tlc_version == "2.20"
    assert p._tlc_rev == "abc1234"


def test_config_extracted():
    p = parse(HEADER)
    assert p._seed == 9876
    assert p._num_workers == 2
    assert p._num_cores == 8
    assert p._heap_size == 4096
    assert p._offheap_size == 64
    assert "breadth-first" in (p._mode or "")


# ---------------------------------------------------------------------------
# Tests — phase transitions
# ---------------------------------------------------------------------------


def test_phase_parsing_after_version():
    p = parse(HEADER)
    assert p.get_current_phase() == TLCPhase.PARSING


def test_phase_checking_after_initial_states():
    output = HEADER + "Finished computing initial states: 3 distinct states generated at 2024-01-01 12:00:00.\n"
    p = parse(output)
    assert p.get_current_phase() == TLCPhase.CHECKING


def test_phase_complete_after_no_error():
    p = parse(HEADER + SUCCESS_TAIL)
    assert p.get_current_phase() == TLCPhase.COMPLETE


def test_phase_failed_on_error():
    p = parse(DEADLOCK)
    assert p.get_current_phase() == TLCPhase.FAILED


def test_phase_temporal_during_liveness():
    p = parse(LIVENESS_VIOLATION)
    # "Finished checking temporal properties" must NOT reset phase back to
    # CHECKING when a violation has already been found (phase = FAILED).
    assert p.get_current_phase() == TLCPhase.FAILED


# ---------------------------------------------------------------------------
# Tests — modules parsed
# ---------------------------------------------------------------------------


def test_modules_parsed():
    p = parse(HEADER)
    modules = p.get_modules_parsed()
    assert len(modules) == 2
    assert any("Foo.tla" in m for m in modules)
    assert any("Bar.tla" in m for m in modules)


# ---------------------------------------------------------------------------
# Tests — progress snapshots
# ---------------------------------------------------------------------------


def test_progress_snapshot():
    p = parse(HEADER + PROGRESS_LINE)
    prog = p.get_latest_progress()
    assert prog is not None
    assert prog.depth == 5
    assert prog.total_states == 100
    assert prog.distinct_states == 42
    assert prog.queue_size == 10
    assert prog.states_per_minute == 50


def test_progress_history_accumulates():
    line2 = (
        "Progress(6) at 2024-01-01 12:00:02: "
        "200 states generated, 80 distinct states found, 5 states left on queue."
    )
    p = parse(HEADER + PROGRESS_LINE + "\n" + line2)
    assert len(p._progress_history) == 2
    assert p._progress_history[1].depth == 6
    assert p._progress_history[1].states_per_minute is None  # no rate on second line


# ---------------------------------------------------------------------------
# Tests — state counts and depth
# ---------------------------------------------------------------------------


def test_final_state_counts():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.total_states == 3157
    assert run.total_distinct_states == 512
    assert run.num_states_queued == 0


def test_state_depth():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.state_depth == 7


def test_duration_extracted():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.duration is None  # duration is set by TLCRun, not parser


# ---------------------------------------------------------------------------
# Tests — coverage
# ---------------------------------------------------------------------------


def test_coverage_entries():
    run = populated_run(HEADER + SUCCESS_TAIL + COVERAGE_BLOCK)
    assert run.coverage is not None
    assert len(run.coverage) == 2
    names = {c.action_name for c in run.coverage}
    assert "Init" in names
    assert "Next" in names
    next_entry = next(c for c in run.coverage if c.action_name == "Next")
    assert next_entry.count == 300
    assert next_entry.module == "Foo"
    assert next_entry.line == 20


# ---------------------------------------------------------------------------
# Tests — error: config not found
# ---------------------------------------------------------------------------


def test_config_not_found_kind():
    run = populated_run(CONFIG_NOT_FOUND)
    assert run.error_kind == "config_not_found"


def test_config_not_found_path():
    run = populated_run(CONFIG_NOT_FOUND)
    # error_msg stores the config file path for this kind
    assert run.error_msg is not None
    assert "Foo.cfg" in run.error_msg


def test_config_not_found_no_diagnostics():
    run = populated_run(CONFIG_NOT_FOUND)
    assert not run.diagnostics


# ---------------------------------------------------------------------------
# Tests — error: semantic error with structured diagnostics
# ---------------------------------------------------------------------------


def test_semantic_error_kind():
    run = populated_run(SEMANTIC_ERROR_WITH_DIAGS)
    assert run.error_kind == "semantic_error"


def test_semantic_error_diagnostic_count():
    run = populated_run(SEMANTIC_ERROR_WITH_DIAGS)
    assert run.diagnostics is not None
    assert len(run.diagnostics) == 2


def test_semantic_error_first_diagnostic():
    run = populated_run(SEMANTIC_ERROR_WITH_DIAGS)
    assert run.diagnostics is not None
    diag = run.diagnostics[0]
    assert diag.module == "Foo"
    assert diag.line_start == 15
    assert diag.col_start == 5
    assert "Unknown operator" in diag.message


def test_semantic_error_second_diagnostic():
    run = populated_run(SEMANTIC_ERROR_WITH_DIAGS)
    assert run.diagnostics is not None
    diag = run.diagnostics[1]
    assert diag.line_start == 30
    assert "Wrong number" in diag.message


def test_semantic_error_diagnostics_deduplicated():
    """Repeated identical diagnostics (TLC reports them once per dependent module)
    should appear only once in the list."""
    doubled = SEMANTIC_ERROR_WITH_DIAGS + """\
line 15, col 5 to line 15, col 12 of module Foo

Unknown operator: Baad

Error: Parsing or semantic analysis failed.
Finished in 0s at (2024-01-01 12:00:00)
"""
    run = populated_run(doubled)
    assert run.diagnostics is not None
    assert len(run.diagnostics) == 2  # still 2, not 3


def test_semantic_error_no_msg():
    """For semantic errors the raw error_msg should be suppressed
    (the diagnostics table is shown instead)."""
    run = populated_run(SEMANTIC_ERROR_WITH_DIAGS)
    assert run.error_msg is None


# ---------------------------------------------------------------------------
# Tests — error: semantic error without structured diagnostics
# ---------------------------------------------------------------------------


def test_semantic_error_no_diags_kind():
    run = populated_run(SEMANTIC_ERROR_NO_DIAGS)
    assert run.error_kind == "semantic_error"


def test_semantic_error_no_diags_empty_list():
    run = populated_run(SEMANTIC_ERROR_NO_DIAGS)
    assert not run.diagnostics


# ---------------------------------------------------------------------------
# Tests — error: deadlock trace
# ---------------------------------------------------------------------------


def test_deadlock_trace_state_count():
    run = populated_run(DEADLOCK)
    assert run.trace is not None
    assert len(run.trace) == 2


def test_deadlock_trace_state1():
    run = populated_run(DEADLOCK)
    assert run.trace is not None
    s1 = run.trace[0]
    assert s1.index == 1
    assert s1.action_name == "Init"
    assert s1.location == "Foo:10"
    assert not s1.is_back_edge
    assert len(s1.variables) == 2
    names = {v.name for v in s1.variables}
    assert "x" in names and "y" in names


def test_deadlock_trace_state1_variable_values():
    run = populated_run(DEADLOCK)
    assert run.trace is not None
    vars_map = {v.name: v.value for v in run.trace[0].variables}
    assert vars_map["x"] == "0"
    assert vars_map["y"] == "1"


def test_deadlock_trace_state2():
    run = populated_run(DEADLOCK)
    assert run.trace is not None
    s2 = run.trace[1]
    assert s2.index == 2
    assert s2.action_name == "Next"
    assert s2.location == "Foo:20"


def test_deadlock_state_counts_still_parsed():
    """State counts should be parsed even when a trace is present."""
    run = populated_run(DEADLOCK)
    assert run.total_states == 5
    assert run.total_distinct_states == 3


# ---------------------------------------------------------------------------
# Tests — error: safety violation trace
# ---------------------------------------------------------------------------


def test_safety_trace_error_msg_captured():
    run = populated_run(SAFETY_VIOLATION)
    # The first Error: line ("Invariant Inv is violated.") becomes error_msg
    assert run.error_msg is not None
    assert "Invariant Inv" in run.error_msg


def test_safety_trace_has_states():
    run = populated_run(SAFETY_VIOLATION)
    assert run.trace is not None
    assert len(run.trace) == 2


def test_safety_trace_variable():
    run = populated_run(SAFETY_VIOLATION)
    assert run.trace is not None
    s2 = run.trace[1]
    assert s2.action_name == "Increment"
    vars_map = {v.name: v.value for v in s2.variables}
    assert vars_map["counter"] == "100"


# ---------------------------------------------------------------------------
# Tests — error: liveness violation with back-edge
# ---------------------------------------------------------------------------


def test_liveness_trace_state_count():
    run = populated_run(LIVENESS_VIOLATION)
    assert run.trace is not None
    assert len(run.trace) == 4  # 3 forward states + 1 back-edge


def test_liveness_trace_initial_predicate():
    run = populated_run(LIVENESS_VIOLATION)
    assert run.trace is not None
    s1 = run.trace[0]
    assert s1.index == 1
    # "<Initial predicate>" → brackets stripped to "Initial predicate"
    assert s1.action_name == "Initial predicate"
    assert s1.location is None
    assert not s1.is_back_edge


def test_liveness_trace_forward_state():
    run = populated_run(LIVENESS_VIOLATION)
    assert run.trace is not None
    s2 = run.trace[1]
    assert s2.action_name == "Start"
    assert s2.location == "Foo:15"
    assert not s2.is_back_edge


def test_liveness_trace_back_edge():
    run = populated_run(LIVENESS_VIOLATION)
    assert run.trace is not None
    back = run.trace[-1]
    assert back.is_back_edge
    assert back.index == 2  # "Back to state 2"
    assert back.action_name == "Start"
    assert back.location == "Foo:15"


# ---------------------------------------------------------------------------
# Tests — multi-line variable values in trace
# ---------------------------------------------------------------------------


def test_multiline_variable_value():
    run = populated_run(MULTILINE_TRACE)
    assert run.trace is not None
    s1 = run.trace[0]
    vars_map = {v.name: v.value for v in s1.variables}
    assert "mapping" in vars_map
    # All three continuation lines should be in the value
    assert "a |-> 1" in vars_map["mapping"]
    assert "b |-> 2" in vars_map["mapping"]
    assert "c |-> 3" in vars_map["mapping"]
    assert vars_map["flag"] == "TRUE"


# ---------------------------------------------------------------------------
# Tests — action name extraction
# ---------------------------------------------------------------------------


def test_action_name_with_arguments():
    """Actions like <ProcessTask({t, u}) line 40 ...> should extract just the name."""
    run = populated_run(ACTION_WITH_ARGS)
    assert run.trace is not None
    s1 = run.trace[0]
    assert s1.action_name == "ProcessTask"
    assert s1.location == "Worker:40"


def test_action_name_stuttering():
    output = """\
Error: Deadlock reached.
Error: The behavior up to this point is:
State 1: Stuttering
Finished in 0s at (2024-01-01 12:00:00)
"""
    run = populated_run(output)
    assert run.trace is not None
    assert run.trace[0].action_name == "Stuttering"
    assert run.trace[0].location is None


# ---------------------------------------------------------------------------
# Tests — populate_run field mapping
# ---------------------------------------------------------------------------


def test_populate_run_version_fields():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.tlc_version == "2.20"
    assert run.tlc_rev == "abc1234"


def test_populate_run_worker_fields():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.num_workers == 2
    assert run.num_cores == 8
    assert run.heap_size == 4096
    assert run.offheap_size == 64


def test_populate_run_modules():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.modules is not None
    assert len(run.modules) == 2


def test_populate_run_no_trace_on_success():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.trace is None


def test_populate_run_no_coverage_when_absent():
    run = populated_run(HEADER + SUCCESS_TAIL)
    assert run.coverage is None
