"""TLC output parsing and display component.

This module provides two main classes:

- :class:`TLCOutputParser`: Parses TLC output line-by-line and extracts structured
  data (version, configuration, progress snapshots, coverage statistics, semantic
  diagnostics, error classification, and error state traces).
- :class:`TLCOutputDisplay`: Renders a Rich live terminal display while TLC is
  running, then prints a formatted summary panel when the run completes.

Error kinds produced by the parser or the exit-code mapper in :mod:`cli.tools.tlc`:

``"config_not_found"``
    The ``.cfg`` model file was not found.  A clean path-only message is shown;
    stats table is suppressed.

``"semantic_error"``
    TLC reported parsing or semantic analysis failures.  Individual diagnostics
    (location + message, deduplicated) are shown in a table; stats table is
    suppressed.

``"deadlock"``
    TLC detected a deadlock (exit code 11).  The error trace is rendered.

``"safety_violation"``
    A safety property (invariant or action property) was violated (exit 12).
    The error trace is rendered.

``"liveness_violation"``
    A liveness / temporal property was violated (exit 13).  The error trace is
    rendered.

``"assumption_violation"``
    An ASSUME clause was violated (exit 10).

``"runtime_error"``
    A runtime exception that is not a config/parse problem (exit 1).

``"unknown"``
    Any other non-zero exit code.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console, ConsoleRenderable, Group, RichCast
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from .tlc import TLCRun


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class TLCPhase(Enum):
    """Phases of a TLC model-checking or simulation run.

    Attributes:
        INIT: TLC has been launched but has not yet produced output.
        PARSING: TLC is parsing TLA+ source files.
        INITIAL_STATES: TLC is computing the set of initial states.
        CHECKING: TLC is performing breadth-first state-space exploration.
        TEMPORAL: TLC is checking temporal (liveness) properties.
        COMPLETE: The run finished without finding any violation.
        FAILED: The run found a violation or terminated with an error.
    """

    INIT = "init"
    PARSING = "parsing"
    INITIAL_STATES = "initial_states"
    CHECKING = "checking"
    TEMPORAL = "temporal"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class TLCProgress:
    """A single progress snapshot extracted from a TLC ``Progress(...)`` line.

    Attributes:
        depth: Current BFS depth reported by TLC.
        timestamp: Wall-clock time of the snapshot as reported by TLC.
        total_states: Cumulative number of states generated so far.
        distinct_states: Number of distinct states found so far.
        states_per_minute: Generation rate in states per minute, or ``None``
            when TLC omits the rate (typically on the final progress line).
        queue_size: Number of states still waiting to be explored.
    """

    depth: int
    timestamp: datetime
    total_states: int
    distinct_states: int
    states_per_minute: Optional[int]
    queue_size: int


@dataclass
class TLCActionCoverage:
    """Coverage data for a single TLA+ action, extracted from ``-coverage`` output.

    Attributes:
        action_name: Name of the TLA+ action.
        module: Name of the TLA+ module that defines the action.
        line: Source line number where the action is defined.
        count: Number of times the action generated at least one new state.
    """

    action_name: str
    module: str
    line: int
    count: int


@dataclass
class TLCDiagnostic:
    """A single semantic or parsing diagnostic reported by TLC.

    Diagnostics appear in the ``Semantic errors:`` sections of TLC output.
    Multiple modules may report the same underlying issue; duplicates are
    removed by the parser before storing.

    Attributes:
        module: Name of the TLA+ module in which the error was detected.
        line_start: First line of the offending source range.
        col_start: First column of the offending source range.
        line_end: Last line of the offending source range.
        col_end: Last column of the offending source range.
        message: Human-readable error description (multi-line text joined
            into a single string).
    """

    module: str
    line_start: int
    col_start: int
    line_end: int
    col_end: int
    message: str


@dataclass
class TLCStateVariable:
    """A single variable binding within a TLC error-trace state.

    Attributes:
        name: Name of the TLA+ variable.
        value: String representation of the variable's value.  May span
            multiple lines if the value is a record, set, or sequence.
    """

    name: str
    value: str


@dataclass
class TLCTraceState:
    """One state in a TLC error trace.

    Attributes:
        index: 1-based position of this state in the forward trace.  For
            back-edge entries in liveness counter-examples, this holds the
            *target* state index (the state the cycle loops back to).
        action_name: Name of the TLA+ action (or ``"Stuttering"``) that led
            to this state.
        location: Formatted source location of the action (e.g. ``"Module:10"``),
            or ``None`` for synthetic actions like Stuttering or Initial predicate.
        variables: Ordered list of variable bindings in this state.
        is_back_edge: ``True`` when this entry represents a liveness back-edge
            (the cycle that closes the infinite loop), ``False`` for a normal
            forward state.
    """

    index: int
    action_name: str
    location: Optional[str]
    variables: list[TLCStateVariable]
    is_back_edge: bool = False


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Compiled pattern used inside the parser to extract action name / location
# from strings like:
#   <Init line 10, col 3 to line 15, col 4 of module Foo>
#   <RegisterTasks({t, u, v}) line 67, col 5 to line 70, col 31 of module Foo>
# The `(?:[^>]*?)` skips optional action arguments before the `line` keyword.
_ACTION_PATTERN = re.compile(r"<(?P<name>\w+)(?:[^>]*?)\s+line\s+(?P<line>\d+).*?of module (?P<module>\w+)>?")


class TLCOutputParser:
    """Parses TLC standard output line-by-line and accumulates structured data.

    Feed each output line with :meth:`feed_line` as TLC produces it.  After
    the process exits, call :meth:`populate_run` to transfer all extracted
    data into a :class:`~cli.tools.tlc.TLCRun` instance.

    The parser classifies detected errors into the following *error kinds*
    stored in ``TLCRun.error_kind``.  For pre-processing errors the kind is
    set by the parser; for runtime violations it is set by
    :meth:`~cli.tools.tlc.TLC._parse_failure` using the exit code.

    Parser-set kinds:
    - ``"config_not_found"``: missing ``.cfg`` file.
    - ``"semantic_error"``: parsing/semantic analysis failures.

    Exit-code-set kinds (see :class:`~cli.tools.tlc.TLC`):
    - ``"deadlock"``, ``"safety_violation"``, ``"liveness_violation"``,
      ``"assumption_violation"``, ``"runtime_error"``, ``"unknown"``.

    Attributes:
        _phase: Current parsing phase.
        _tlc_version: TLC version string (e.g. ``"2.19"``).
        _tlc_rev: TLC git revision hash.
        _seed: Fingerprint seed used for this run.
        _num_workers: Number of TLC worker threads.
        _num_cores: Number of available CPU cores as reported by TLC.
        _heap_size: JVM heap size in MB.
        _offheap_size: JVM off-heap size in MB.
        _mode: Running mode string (e.g. ``"breadth-first search Model-Checking"``).
        _modules_parsed: Ordered list of ``.tla`` file paths that TLC parsed.
        _initial_states: Number of distinct initial states computed.
        _progress_history: All :class:`TLCProgress` snapshots collected so far.
        _coverage: All :class:`TLCActionCoverage` entries collected so far.
        _in_coverage_block: Whether the parser is currently inside a coverage block.
        _duration_seconds: Run duration in seconds as reported by TLC's final line.
        _diagnostics: Deduplicated list of :class:`TLCDiagnostic` objects.
        _error_lines: Raw lines of the current TLC error block (pre-trace).
        _error_kind: Classified error kind.
        _in_trace: Whether the parser is currently consuming an error state trace.
        _trace_states: All fully-parsed :class:`TLCTraceState` objects.
    """

    regex: dict[str, re.Pattern] = {
        "version": re.compile(r"TLC2 Version (?P<tlc_version>[\d.]+) of .+? \(rev: (?P<tlc_rev>[a-f0-9]+)\)"),
        "config": re.compile(
            r"Running (?P<mode>.+?) with fp \d+ and seed (?P<seed>\d+)"
            r" with (?P<num_workers>\d+) workers? on (?P<num_cores>\d+) cores?"
            r" with (?P<heap_size>\d+)MB heap and (?P<offheap_size>\d+)MB offheap"
        ),
        "parsing": re.compile(r"^Parsing file (?P<filepath>.+\.tla)"),
        "initial_states": re.compile(r"Finished computing initial states: (?P<count>[\d,]+) distinct state"),
        "progress": re.compile(
            r"Progress\((?P<depth>\d+)\) at (?P<ts>[\d\-: ]+):\s*"
            r"(?P<total>[\d,]+) states generated"
            r"(?:\s+\((?P<rate>[\d,]+) s/min\))?"
            r",\s*(?P<distinct>[\d,]+) distinct states found"
            r".*?(?P<queue>[\d,]+) states left on queue"
        ),
        "temporal_check": re.compile(r"Checking \d+ branches of temporal properties"),
        "temporal_done": re.compile(r"Finished checking temporal properties"),
        "completed": re.compile(r"Model checking completed\. No error has been found\."),
        "finished": re.compile(r"^Finished in (?P<seconds>\d+)s"),
        "state_count": re.compile(
            r"^(?P<total_states>[\d,]+) states generated,"
            r" (?P<distinct_states>[\d,]+) distinct states found,"
            r" (?P<queue>[\d,]+) states left on queue\.$"
        ),
        "state_depth": re.compile(r"The depth of the complete state graph search is (?P<state_depth>[\d,]+)"),
        "coverage_header": re.compile(r"^Coverage at (?P<ts>[\d\-: ]+):$"),
        "coverage_action": re.compile(
            r'<"(?P<action>[^"]+)" line (?P<line>\d+).*? of module (?P<module>\w+)>'
            r":\s*(?P<count>\d+) states generated"
        ),
        "simulation_progress": re.compile(r"Simulation: (?P<traces>\d+) traces? generated"),
        # Error and diagnostic patterns
        "error_start": re.compile(r"^Error:\s*(?P<msg>.*)$"),
        "diagnostic_loc": re.compile(
            r"^line (?P<ls>\d+), col (?P<cs>\d+)"
            r" to line (?P<le>\d+), col (?P<ce>\d+)"
            r" of module (?P<mod>\w+)"
        ),
        "exception_type": re.compile(r"^The exception was a (?P<exc>\S+)"),
        "config_file_path": re.compile(r"configuration file (?P<path>.+?):\s*$"),
        # Trace patterns — TLC uses two different trace-header wordings:
        # safety/deadlock: "The behavior up to this point is:"
        # liveness:        "The following behavior constitutes a counter-example:"
        "state_header": re.compile(r"^State (?P<idx>\d+): (?P<desc>.+)$"),
        "back_edge": re.compile(r"^Back to state (?P<idx>\d+): (?P<desc>.*)$"),
        "state_var": re.compile(r"^/\\ (?P<name>[\w.]+) = (?P<value>.*)$"),
        "state_var_bare": re.compile(r"^(?P<name>[A-Za-z_]\w*) = (?P<value>.*)$"),
    }

    def __init__(self) -> None:
        """Initialise the parser with empty state."""
        self._phase: TLCPhase = TLCPhase.INIT
        self._tlc_version: Optional[str] = None
        self._tlc_rev: Optional[str] = None
        self._seed: Optional[int] = None
        self._num_workers: Optional[int] = None
        self._num_cores: Optional[int] = None
        self._heap_size: Optional[int] = None
        self._offheap_size: Optional[int] = None
        self._mode: Optional[str] = None
        self._modules_parsed: list[str] = []
        self._initial_states: Optional[int] = None
        self._progress_history: list[TLCProgress] = []
        self._final_total_states: Optional[int] = None
        self._final_distinct_states: Optional[int] = None
        self._final_queue_size: Optional[int] = None
        self._state_depth: Optional[int] = None
        self._coverage: list[TLCActionCoverage] = []
        self._in_coverage_block: bool = False
        self._duration_seconds: Optional[int] = None
        self._simulation_traces: Optional[int] = None

        # Diagnostic (semantic/parsing error) tracking
        self._diagnostics: list[TLCDiagnostic] = []
        self._seen_diagnostics: set[tuple] = set()  # dedup key set
        self._pending_loc: Optional[tuple[str, int, int, int, int]] = None
        self._pending_msg_lines: list[str] = []

        # Generic error block tracking
        self._error_lines: list[str] = []
        self._in_error_block: bool = False
        self._exception_type: Optional[str] = None
        self._config_file_path: Optional[str] = None
        self._error_kind: Optional[str] = None

        # Error trace tracking
        self._in_trace: bool = False
        self._trace_states: list[TLCTraceState] = []
        self._current_state_idx: Optional[int] = None
        self._current_state_action_raw: Optional[str] = None
        self._current_state_vars: list[TLCStateVariable] = []
        self._current_is_back_edge: bool = False
        self._current_var_name: Optional[str] = None
        self._current_var_value_lines: list[str] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def feed_line(self, line: str) -> None:
        """Process one line of raw TLC output and update internal state.

        Args:
            line: A single line from TLC's standard output (without trailing newline).
        """
        stripped = line.strip()

        # Version / revision
        m = self.regex["version"].search(stripped)
        if m:
            self._tlc_version = m.group("tlc_version")
            self._tlc_rev = m.group("tlc_rev")
            self._phase = TLCPhase.PARSING
            return

        # Runtime configuration
        m = self.regex["config"].search(stripped)
        if m:
            self._mode = m.group("mode")
            self._seed = int(m.group("seed"))
            self._num_workers = int(m.group("num_workers"))
            self._num_cores = int(m.group("num_cores"))
            self._heap_size = int(m.group("heap_size"))
            self._offheap_size = int(m.group("offheap_size"))
            return

        # File parsing — only match lines starting with "Parsing file"
        m = self.regex["parsing"].match(stripped)
        if m:
            self._modules_parsed.append(m.group("filepath"))
            self._phase = TLCPhase.PARSING
            return

        # Diagnostic location line — process before the generic error block
        # handler so that semantic errors are structured even when they come
        # right before the "Error: Parsing or semantic analysis failed." line.
        m = self.regex["diagnostic_loc"].match(stripped)
        if m:
            self._flush_pending_diagnostic()
            self._pending_loc = (
                m.group("mod"),
                int(m.group("ls")),
                int(m.group("cs")),
                int(m.group("le")),
                int(m.group("ce")),
            )
            self._pending_msg_lines = []
            return

        # Accumulate message lines for a pending diagnostic.
        # The TLC format is:
        #   <location line>
        #   <blank>
        #   <message line(s)>
        #   <blank>     ← flush here
        if self._pending_loc is not None:
            if stripped and not stripped.startswith("***"):
                self._pending_msg_lines.append(stripped)
            elif not stripped and self._pending_msg_lines:
                # Empty line after we have message content → commit
                self._flush_pending_diagnostic()
            # (blank lines before any message content are silently skipped)
            return

        # Initial states computed
        m = self.regex["initial_states"].search(stripped)
        if m:
            self._initial_states = int(m.group("count").replace(",", ""))
            self._phase = TLCPhase.CHECKING
            return

        # Progress snapshot
        m = self.regex["progress"].search(stripped)
        if m:
            rate_str = m.group("rate")
            self._progress_history.append(
                TLCProgress(
                    depth=int(m.group("depth")),
                    timestamp=self._parse_timestamp(m.group("ts")),
                    total_states=int(m.group("total").replace(",", "")),
                    distinct_states=int(m.group("distinct").replace(",", "")),
                    states_per_minute=int(rate_str.replace(",", "")) if rate_str else None,
                    queue_size=int(m.group("queue").replace(",", "")),
                )
            )
            self._phase = TLCPhase.CHECKING
            return

        # Temporal property checking
        if self.regex["temporal_check"].search(stripped):
            self._phase = TLCPhase.TEMPORAL
            return

        if self.regex["temporal_done"].search(stripped):
            # Do not reset the phase when we are already in a failed state —
            # liveness counter-examples emit this line inside the error block.
            if self._phase != TLCPhase.FAILED:
                self._phase = TLCPhase.CHECKING
            return

        # Final state count line
        m = self.regex["state_count"].match(stripped)
        if m:
            self._final_total_states = int(m.group("total_states").replace(",", ""))
            self._final_distinct_states = int(m.group("distinct_states").replace(",", ""))
            self._final_queue_size = int(m.group("queue").replace(",", ""))
            return

        # State depth
        m = self.regex["state_depth"].search(stripped)
        if m:
            self._state_depth = int(m.group("state_depth").replace(",", ""))
            return

        # ---------------------------------------------------------------
        # Error block handling
        # ---------------------------------------------------------------

        m = self.regex["error_start"].match(stripped)
        if m:
            first_msg = m.group("msg").strip()
            self._phase = TLCPhase.FAILED
            self._in_coverage_block = False
            self._flush_pending_diagnostic()

            if "Parsing or semantic analysis failed" in first_msg:
                # The diagnostics are already captured above; just classify.
                self._error_kind = self._error_kind or "semantic_error"
                return

            # Detect the start of a state trace.
            # TLC uses "The behavior up to this point is:" for safety/deadlock
            # violations and "The following behavior constitutes a
            # counter-example:" for liveness violations.
            if "behavior up to this point is" in first_msg or "behavior constitutes a counter-example" in first_msg:
                # Flush any previous in-block state before starting trace
                self._flush_current_var()
                self._flush_current_state()
                self._in_trace = True
                return

            # All other TLC exceptions
            self._in_error_block = True
            if first_msg:
                # The config file path sometimes appears on the same Error: line
                # (e.g. "Failed to open the configuration file /Foo.cfg:").
                m2 = self.regex["config_file_path"].search(first_msg)
                if m2:
                    self._config_file_path = m2.group("path").strip()
                self._error_lines.append(first_msg)
            return

        if self._in_error_block:
            # Trace lines come after the "behavior up to this point is" Error: line,
            # which is still inside the same error block.
            if self._in_trace:
                # Check for the closing "Finished in Ns" line first
                m2 = self.regex["finished"].match(stripped)
                if m2:
                    self._in_error_block = False
                    self._in_trace = False
                    self._flush_current_var()
                    self._flush_current_state()
                    self._duration_seconds = int(m2.group("seconds"))
                    self._classify_exception()
                    return
                self._parse_trace_line(stripped)
                return

            if self.regex["finished"].match(stripped):
                self._in_error_block = False
                m2 = self.regex["finished"].match(stripped)
                if m2:
                    self._duration_seconds = int(m2.group("seconds"))
                self._classify_exception()
                return
            if stripped:
                # Detect exception class
                m2 = self.regex["exception_type"].match(stripped)
                if m2:
                    self._exception_type = m2.group("exc")
                # Detect config file path
                m2 = self.regex["config_file_path"].search(stripped)
                if m2:
                    self._config_file_path = m2.group("path").strip()
                self._error_lines.append(stripped)
            return

        # ---------------------------------------------------------------
        # Success / completion
        # ---------------------------------------------------------------

        if self.regex["completed"].search(stripped):
            self._phase = TLCPhase.COMPLETE
            return

        m = self.regex["finished"].match(stripped)
        if m:
            self._duration_seconds = int(m.group("seconds"))
            return

        # Coverage block header
        m = self.regex["coverage_header"].match(stripped)
        if m:
            self._in_coverage_block = True
            return

        if self._in_coverage_block:
            m = self.regex["coverage_action"].search(stripped)
            if m:
                self._coverage.append(
                    TLCActionCoverage(
                        action_name=m.group("action"),
                        module=m.group("module"),
                        line=int(m.group("line")),
                        count=int(m.group("count")),
                    )
                )
                return
            if stripped == "" or not stripped.startswith("<"):
                self._in_coverage_block = False

        # Simulation progress
        m = self.regex["simulation_progress"].search(stripped)
        if m:
            self._simulation_traces = int(m.group("traces"))

    def get_current_phase(self) -> TLCPhase:
        """Return the current parsing phase.

        Returns:
            The :class:`TLCPhase` that best describes TLC's current activity.
        """
        return self._phase

    def get_latest_progress(self) -> Optional[TLCProgress]:
        """Return the most recent progress snapshot, or ``None`` if none yet.

        Returns:
            The last :class:`TLCProgress` entry, or ``None``.
        """
        return self._progress_history[-1] if self._progress_history else None

    def get_modules_parsed(self) -> list[str]:
        """Return the list of ``.tla`` file paths parsed so far.

        Returns:
            Ordered list of absolute file paths as strings.
        """
        return list(self._modules_parsed)

    def populate_run(self, tlc_run: "TLCRun") -> None:
        """Write all extracted data into a :class:`~cli.tools.tlc.TLCRun` instance.

        This method should be called after the TLC process has exited.  Any
        pending diagnostic or trace state that was never terminated by a blank
        line is flushed before returning.

        Args:
            tlc_run: The :class:`~cli.tools.tlc.TLCRun` object to populate in-place.
        """
        # Flush any diagnostic whose terminating blank line was absent.
        self._flush_pending_diagnostic()
        # Flush any open trace state (process may have exited without blank line).
        self._flush_current_var()
        self._flush_current_state()

        tlc_run.tlc_version = self._tlc_version
        tlc_run.tlc_rev = self._tlc_rev
        tlc_run.seed = self._seed
        tlc_run.num_workers = self._num_workers
        tlc_run.num_cores = self._num_cores
        tlc_run.heap_size = self._heap_size
        tlc_run.offheap_size = self._offheap_size
        tlc_run.mode = self._mode
        tlc_run.modules = self._modules_parsed if self._modules_parsed else None

        if self._final_total_states is not None:
            tlc_run.total_states = self._final_total_states
        if self._final_distinct_states is not None:
            tlc_run.total_distinct_states = self._final_distinct_states
        if self._final_queue_size is not None:
            tlc_run.num_states_queued = self._final_queue_size
        if self._state_depth is not None:
            tlc_run.state_depth = self._state_depth

        tlc_run.progress_history = self._progress_history if self._progress_history else None
        tlc_run.coverage = self._coverage if self._coverage else None
        tlc_run.diagnostics = self._diagnostics if self._diagnostics else None
        tlc_run.error_kind = self._error_kind
        tlc_run.trace = self._trace_states if self._trace_states else None

        # Set error_msg based on error kind
        if self._error_kind == "config_not_found":
            # Store only the clean path; display handles the label
            tlc_run.error_msg = self._config_file_path
        elif self._error_kind == "semantic_error":
            # Diagnostics table is shown instead of raw error_msg
            tlc_run.error_msg = None
        elif self._error_lines:
            tlc_run.error_msg = "\n".join(self._error_lines)

    # ------------------------------------------------------------------
    # Private helpers — diagnostics
    # ------------------------------------------------------------------

    def _flush_pending_diagnostic(self) -> None:
        """Commit a pending diagnostic to the deduplicated list.

        Does nothing when there is no pending location or no message lines
        have been accumulated yet.
        """
        if self._pending_loc is None or not self._pending_msg_lines:
            self._pending_loc = None
            self._pending_msg_lines = []
            return

        mod, ls, cs, le, ce = self._pending_loc
        message = " ".join(self._pending_msg_lines)
        dedup_key = (mod, ls, cs, message)
        if dedup_key not in self._seen_diagnostics:
            self._seen_diagnostics.add(dedup_key)
            self._diagnostics.append(
                TLCDiagnostic(
                    module=mod,
                    line_start=ls,
                    col_start=cs,
                    line_end=le,
                    col_end=ce,
                    message=message,
                )
            )
        self._pending_loc = None
        self._pending_msg_lines = []

    def _classify_exception(self) -> None:
        """Classify the completed error block based on the exception type.

        Should be called when the ``Finished in`` line closes the error block.
        """
        if self._exception_type and "ConfigFileException" in self._exception_type:
            self._error_kind = "config_not_found"
        # Other kinds (deadlock, safety, etc.) are set by exit code in tlc.py

    # ------------------------------------------------------------------
    # Private helpers — trace parsing
    # ------------------------------------------------------------------

    def _parse_trace_line(self, stripped: str) -> None:
        """Process one line while inside an error state trace.

        Args:
            stripped: The line, stripped of leading/trailing whitespace.
        """
        if not stripped:
            # Blank line: flush current variable then current state
            self._flush_current_var()
            self._flush_current_state()
            return

        # State header: "State N: <Action ...>" or "State N: Stuttering"
        m = self.regex["state_header"].match(stripped)
        if m:
            self._flush_current_var()
            self._flush_current_state()
            self._current_state_idx = int(m.group("idx"))
            self._current_state_action_raw = m.group("desc").strip()
            self._current_state_vars = []
            self._current_is_back_edge = False
            return

        # Back-edge header (liveness traces): "Back to state N: <Action ...>"
        m = self.regex["back_edge"].match(stripped)
        if m:
            self._flush_current_var()
            self._flush_current_state()
            # Store the target state index; _flush_current_state will mark it
            # as a back-edge using the sentinel value stored on the instance.
            desc = m.group("desc").strip()
            self._current_state_idx = int(m.group("idx"))
            self._current_state_action_raw = desc or "Back-edge"
            self._current_is_back_edge = True
            self._current_state_vars = []
            return

        # Variable line: "/\ name = value" (multi-variable traces)
        m = self.regex["state_var"].match(stripped)
        if m:
            self._flush_current_var()
            self._current_var_name = m.group("name")
            initial_value = m.group("value")
            self._current_var_value_lines = [initial_value] if initial_value else []
            return

        # Bare "name = value" (single-variable traces — TLC omits the "/\ " prefix)
        if self._current_state_idx is not None:
            m = self.regex["state_var_bare"].match(stripped)
            if m:
                self._flush_current_var()
                self._current_var_name = m.group("name")
                initial_value = m.group("value")
                self._current_var_value_lines = [initial_value] if initial_value else []
                return

        # Continuation line for a multi-line variable value
        if self._current_var_name is not None:
            self._current_var_value_lines.append(stripped)

    def _flush_current_var(self) -> None:
        """Commit the in-progress variable binding to the current state's variable list."""
        if self._current_var_name is not None:
            value = "\n".join(self._current_var_value_lines)
            self._current_state_vars.append(TLCStateVariable(name=self._current_var_name, value=value))
        self._current_var_name = None
        self._current_var_value_lines = []

    def _flush_current_state(self) -> None:
        """Commit the in-progress trace state to the trace list."""
        if self._current_state_idx is not None:
            action_name, location = self._parse_action_string(self._current_state_action_raw or "")
            self._trace_states.append(
                TLCTraceState(
                    index=self._current_state_idx,
                    action_name=action_name,
                    location=location,
                    variables=list(self._current_state_vars),
                    is_back_edge=self._current_is_back_edge,
                )
            )
        self._current_state_idx = None
        self._current_state_action_raw = None
        self._current_state_vars = []
        self._current_is_back_edge = False

    @staticmethod
    def _parse_action_string(raw: str) -> tuple[str, Optional[str]]:
        """Extract an action name and formatted location from a TLC state-header string.

        Args:
            raw: The raw description string from a ``State N: <...>`` line,
                e.g. ``"<Init line 10, col 3 to line 15, col 4 of module Foo>"``.

        Returns:
            A ``(action_name, location)`` tuple.  *location* is formatted as
            ``"Module:line"`` when the raw string contains source information,
            or ``None`` otherwise (e.g. for ``"Stuttering"``).
        """
        m = _ACTION_PATTERN.match(raw)
        if m:
            return m.group("name"), f"{m.group('module')}:{m.group('line')}"
        # Strip angle brackets from synthetic states like "<Initial predicate>"
        # so the display is consistent with named-action states.
        if raw.startswith("<") and raw.endswith(">"):
            return raw[1:-1], None
        # "Stuttering", "Back-edge", etc.
        return raw, None

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        """Parse a TLC-formatted timestamp string into a :class:`datetime`.

        TLC emits timestamps in the format ``YYYY-MM-DD HH:MM:SS``.

        Args:
            ts_str: Raw timestamp string from TLC output.

        Returns:
            Parsed :class:`datetime` object, or the current time if parsing fails.
        """
        try:
            return datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.now()


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

_PHASE_LABELS: dict[TLCPhase, str] = {
    TLCPhase.INIT: "Starting TLC...",
    TLCPhase.PARSING: "Parsing TLA+ modules",
    TLCPhase.INITIAL_STATES: "Computing initial states",
    TLCPhase.CHECKING: "Exploring state space",
    TLCPhase.TEMPORAL: "Checking temporal properties",
    TLCPhase.COMPLETE: "Complete",
    TLCPhase.FAILED: "Failed",
}

# Error kinds that represent pre-processing failures (before any states are explored).
# For these kinds the statistics table is suppressed.
_PREPROCESSING_ERROR_KINDS = frozenset({"config_not_found", "semantic_error"})

# Error kinds that carry an error state trace.
_TRACE_ERROR_KINDS = frozenset({"deadlock", "safety_violation", "liveness_violation", "assumption_violation"})


class TLCOutputDisplay:
    """Rich live terminal display for a TLC run.

    Use this class as a context manager.  While the ``with`` block is active a
    :class:`~rich.live.Live` renderable is updated each time :meth:`update` is
    called.  After the block exits, call :meth:`show_summary` to print a static
    summary panel.

    Example::

        parser = TLCOutputParser()
        with TLCOutputDisplay(console, "MyModule") as display:
            for line in process.stdout:
                parser.feed_line(line.rstrip())
                display.update(parser)
        process.wait()
        parser.populate_run(tlc_run)
        display.show_summary(tlc_run, run_dir)

    Args:
        console: Rich :class:`~rich.console.Console` used for all output.
        module_name: Short name of the TLA+ module being checked, shown in the
            panel title.
        interactive: When ``True`` (default) use a Rich Live display.  When
            ``False`` each significant progress change is printed as a new line
            instead (suitable for non-TTY environments or ``--no-progress``).
        silent: When ``True`` suppress all output, including the summary panel.
            Use this when the caller will emit structured output (e.g. JSON).
    """

    def __init__(
        self,
        console: Console,
        module_name: str,
        *,
        interactive: bool = True,
        silent: bool = False,
    ) -> None:
        self._console = console
        self._module_name = module_name
        self._interactive = interactive
        self._silent = silent
        self._live: Optional[Live] = None
        # Plain-mode state tracking
        self._last_phase: Optional[TLCPhase] = None
        self._last_depth: Optional[int] = None

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "TLCOutputDisplay":
        """Start the Rich Live display (no-op in silent or plain mode)."""
        if not self._silent and self._interactive:
            self._live = Live(
                self._render(TLCPhase.INIT, None),
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the Rich Live display."""
        if self._live is not None:
            self._live.__exit__(exc_type, exc_val, exc_tb)
            self._live = None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, parser: TLCOutputParser) -> None:
        """Refresh the display based on the latest parser state.

        In interactive mode updates the Live renderable in-place.  In plain
        mode prints a new line whenever the phase or depth changes.  In silent
        mode is a no-op.

        Args:
            parser: The :class:`TLCOutputParser` whose current state should be
                reflected in the display.
        """
        if self._silent:
            return
        phase = parser.get_current_phase()
        progress = parser.get_latest_progress()
        if self._interactive:
            if self._live is not None:
                self._live.update(self._render(phase, progress))
        else:
            if phase != self._last_phase:
                self._last_phase = phase
                label = _PHASE_LABELS.get(phase, phase.value)
                self._console.print(f"[dim]{self._module_name}[/dim] · {label}")
            elif progress is not None and progress.depth != self._last_depth:
                self._last_depth = progress.depth
                self._console.print(
                    f"[dim]{self._module_name}[/dim] · "
                    f"depth {progress.depth}, "
                    f"{progress.total_states:,} states, "
                    f"{progress.distinct_states:,} distinct"
                )

    # ------------------------------------------------------------------
    # Summary panel
    # ------------------------------------------------------------------

    def show_summary(self, tlc_run: "TLCRun", run_dir: Optional[Path] = None) -> None:
        """Print a static Rich panel summarising the completed TLC run.

        No-op when the display is in silent mode.


        The panel content adapts to the error kind:

        - ``config_not_found``: displays the missing file path; no stats.
        - ``semantic_error``: diagnostics table; no stats.
        - ``deadlock`` / ``safety_violation`` / ``liveness_violation`` /
          ``assumption_violation``: error type + error trace table + stats.
        - ``runtime_error`` / ``unknown``: raw error block verbatim + stats.

        The footer always shows the path to the full TLC log file.

        This should be called *after* the Live context has exited and
        :meth:`~TLCOutputParser.populate_run` has been called.

        Args:
            tlc_run: Fully populated :class:`~cli.tools.tlc.TLCRun` instance.
            run_dir: Directory where the run artefacts (log, JSON) were saved.
                When provided, the path to ``tlc.log`` is shown at the bottom.
        """
        if self._silent:
            return
        success = tlc_run.success
        title_color = "green" if success else "red"
        status_icon = "[green]✓[/green]" if success else "[red]✗[/red]"

        content_parts: list[ConsoleRenderable | RichCast | str] = []

        if success:
            content_parts.append(Text.from_markup(f"{status_icon} Model checking completed. No error has been found."))
        else:
            content_parts.extend(self._render_error(tlc_run, status_icon))

        error_kind = tlc_run.error_kind or "unknown"
        show_stats = success or error_kind not in _PREPROCESSING_ERROR_KINDS

        if show_stats:
            stats_table = self._build_stats_table(tlc_run)
            if stats_table.row_count:
                content_parts.append(Text(""))
                content_parts.append(stats_table)

        # Coverage table (on success with --coverage, or when collected on failure)
        if tlc_run.coverage:
            content_parts.append(Text(""))
            cov_table = Table(title="Action Coverage", show_header=True, header_style="bold")
            cov_table.add_column("Action", style="cyan")
            cov_table.add_column("Module", style="dim")
            cov_table.add_column("Line", justify="right", style="dim")
            cov_table.add_column("States generated", justify="right")
            for entry in sorted(tlc_run.coverage, key=lambda e: -e.count):
                cov_table.add_row(
                    entry.action_name,
                    entry.module,
                    str(entry.line),
                    f"{entry.count:,}",
                )
            content_parts.append(cov_table)

        # Log file footer
        if run_dir is not None:
            content_parts.append(Text(""))
            content_parts.append(Text.from_markup(f"[dim]See the full TLC logs here:[/dim] {run_dir / 'tlc.log'}"))

        title = f"[bold {title_color}]TLC — {self._module_name}[/bold {title_color}]"
        self._console.print(Panel(Group(*content_parts), title=title, expand=False))

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _render_error(self, tlc_run: "TLCRun", status_icon: str) -> list[ConsoleRenderable | RichCast | str]:
        """Build the error section of the summary panel.

        Returns a list of Rich renderables to be included in the panel's
        content group.

        Args:
            tlc_run: Populated :class:`~cli.tools.tlc.TLCRun` instance.
            status_icon: Pre-formatted Rich markup icon string (``✗`` in red).
        """
        parts: list[ConsoleRenderable | RichCast | str] = []
        error_kind = tlc_run.error_kind or "unknown"
        error_type = tlc_run.error_type or "Error"

        if error_kind == "config_not_found":
            parts.append(Text.from_markup(f"{status_icon} [red]Configuration file not found[/red]"))
            if tlc_run.error_msg:
                parts.append(Text(""))
                parts.append(Text.from_markup(f"  [dim]Path:[/dim] {tlc_run.error_msg}"))
            parts.append(Text.from_markup("  [dim]Hint:[/dim] Create the .cfg file or pass --model-path."))

        elif error_kind == "semantic_error":
            if tlc_run.diagnostics:
                n = len(tlc_run.diagnostics)
                noun = "issue" if n == 1 else "issues"
                parts.append(Text.from_markup(f"{status_icon} [red]Semantic {'error' if n == 1 else 'errors'} — {n} {noun}[/red]"))
                parts.append(Text(""))
                parts.append(self._build_diagnostics_table(tlc_run.diagnostics))
            else:
                parts.append(Text.from_markup(f"{status_icon} [red]Parsing or semantic analysis failed[/red]"))
                parts.append(Text.from_markup("  [dim]Hint:[/dim] See the log file below for detailed error messages."))

        elif error_kind in _TRACE_ERROR_KINDS:
            parts.append(Text.from_markup(f"{status_icon} [red]{error_type}[/red]"))
            if tlc_run.error_msg:
                parts.append(Text(""))
                parts.append(Text(tlc_run.error_msg, style="red dim"))
            if tlc_run.trace:
                parts.append(Text(""))
                parts.append(self._build_trace_table(tlc_run.trace))

        else:
            # runtime_error, unknown, or any unrecognised kind
            parts.append(Text.from_markup(f"{status_icon} [red]{error_type}[/red]"))
            if tlc_run.error_msg:
                parts.append(Text(""))
                parts.append(Text.from_markup("[dim]Error details:[/dim]"))
                parts.append(Text(tlc_run.error_msg, style="red"))

        return parts

    @staticmethod
    def _build_stats_table(tlc_run: "TLCRun") -> Table:
        """Build the run statistics grid table.

        Args:
            tlc_run: Fully populated :class:`~cli.tools.tlc.TLCRun` instance.

        Returns:
            A :class:`~rich.table.Table` (grid layout) with run statistics.
        """
        stats_table = Table.grid(padding=(0, 2))
        stats_table.add_column(style="dim", justify="right")
        stats_table.add_column(justify="right")

        if tlc_run.total_states is not None:
            stats_table.add_row("States generated:", f"{tlc_run.total_states:,}")
        if tlc_run.total_distinct_states is not None:
            stats_table.add_row("Distinct states:", f"{tlc_run.total_distinct_states:,}")
        if tlc_run.num_states_queued is not None:
            stats_table.add_row("States in queue:", f"{tlc_run.num_states_queued:,}")
        if tlc_run.state_depth is not None:
            stats_table.add_row("Graph depth:", str(tlc_run.state_depth))
        if tlc_run.duration is not None:
            total_seconds = int(tlc_run.duration.total_seconds())
            stats_table.add_row("Duration:", f"{total_seconds}s")
        if tlc_run.num_workers is not None:
            stats_table.add_row("Workers:", str(tlc_run.num_workers))
        if tlc_run.tlc_version is not None:
            stats_table.add_row("TLC version:", tlc_run.tlc_version)

        return stats_table

    @staticmethod
    def _build_diagnostics_table(diagnostics: list[TLCDiagnostic]) -> Table:
        """Build a Rich table for a list of :class:`TLCDiagnostic` objects.

        Args:
            diagnostics: Non-empty list of diagnostics to display.

        Returns:
            A :class:`~rich.table.Table` ready to include in a panel.
        """
        table = Table(show_header=True, header_style="bold", show_lines=True, expand=False)
        table.add_column("Module", style="cyan", no_wrap=True)
        table.add_column("Location", style="dim", no_wrap=True)
        table.add_column("Message")
        for d in diagnostics:
            loc = f"line {d.line_start}, col {d.col_start}"
            table.add_row(d.module, loc, d.message)
        return table

    @staticmethod
    def _build_trace_table(trace: list[TLCTraceState]) -> Table:
        """Build a Rich table rendering of an error state trace.

        Each row represents one state in the trace.  The *Variables* column
        contains the variable assignments for that state, one per line.

        Args:
            trace: Ordered list of :class:`TLCTraceState` objects.

        Returns:
            A :class:`~rich.table.Table` ready to include in a panel.
        """
        table = Table(
            title="Error Trace",
            show_header=True,
            header_style="bold",
            show_lines=True,
            expand=False,
        )
        table.add_column("#", style="cyan", no_wrap=True, justify="right")
        table.add_column("Action", no_wrap=True)
        table.add_column("Variables")

        for state in trace:
            # State number cell: "← N" for back-edges, "N" otherwise
            if state.is_back_edge:
                index_cell = Text.from_markup(f"[dim]← {state.index}[/dim]")
            else:
                index_cell = Text(str(state.index))

            # Action cell: action name + optional dim location
            action_lines = [state.action_name]
            if state.location:
                action_lines.append(f"[dim]{state.location}[/dim]")
            action_cell = Text.from_markup("\n".join(action_lines))

            # Variables cell: one "name = value" entry per line
            if state.variables:
                vars_cell = "\n".join(f"{v.name} = {v.value}" for v in state.variables)
            else:
                vars_cell = "[dim](no variables)[/dim]"

            table.add_row(index_cell, action_cell, vars_cell)

        return table

    def _render(self, phase: TLCPhase, progress: Optional[TLCProgress]) -> Group:
        """Build the live renderable for the current parser state.

        Args:
            phase: Current :class:`TLCPhase`.
            progress: Latest :class:`TLCProgress` snapshot, or ``None``.

        Returns:
            A :class:`~rich.console.Group` suitable for :class:`~rich.live.Live`.
        """
        label = _PHASE_LABELS.get(phase, phase.value)

        if progress is not None:
            spinner_text = f"{label} — depth {progress.depth}, {progress.total_states:,} states, {progress.distinct_states:,} distinct"
        else:
            spinner_text = label

        spinner = Spinner("dots", text=f"[bold]{self._module_name}[/bold] · {spinner_text}")
        return Group(spinner)
