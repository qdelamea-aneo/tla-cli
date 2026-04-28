"""TLAPS (TLA+ Proof System) prover wrapper.

This module wraps the ``tlapm`` binary and parses its structured toolbox
output format (``--toolbox 0 0``).  Each proof obligation is tracked
individually; a Rich live display shows proving progress.

Toolbox protocol:
    Each message is delimited by ``@!!BEGIN`` / ``@!!END`` lines.
    Fields inside a block use the format ``@!!key:value``.  Multi-line
    values (e.g. ``@!!obl:``) continue on subsequent lines until the next
    ``@!!`` line or ``@!!END``.

Classes:
    TLAPMObligation: Data for a single proof obligation.
    TLAPMRun: Aggregated results of a tlapm invocation.
    TLAPMOutputParser: Parses tlapm toolbox output line-by-line.
    TLAPMOutputDisplay: Rich live display + summary for a tlapm run.
    TLAPM: Tool class that invokes tlapm and returns a TLAPMRun.
"""

import os
import re
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from logging import Logger
from pathlib import Path
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from .base import Tool

# ---------------------------------------------------------------------------
# Obligation statuses
# ---------------------------------------------------------------------------

#: Obligation status strings emitted by tlapm.
TO_BE_PROVED = "to be proved"
BEING_PROVED = "being proved"
PROVED = "proved"
TRIVIAL = "trivial"
FAILED = "failed"
OMITTED = "omitted"
INTERRUPTED = "interrupted"
UNKNOWN = "unknown"

#: Statuses that count as "done" (not pending).
_FINAL_STATUSES = {PROVED, TRIVIAL, FAILED, OMITTED, INTERRUPTED, UNKNOWN}
#: Statuses that count as "success".
_SUCCESS_STATUSES = {PROVED, TRIVIAL}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_loc(loc: str) -> Optional[tuple[int, int, int, int]]:
    """Parse a tlapm location string ``"l1:c1:l2:c2"`` into a 4-tuple.

    Returns ``None`` when the string is absent or malformed.
    """
    parts = loc.split(":")
    if len(parts) == 4:
        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TLAPMObligation:
    """A single proof obligation as reported by tlapm.

    Attributes:
        id: Numeric obligation identifier.
        loc: Source location string ``"line1:col1:line2:col2"``.
        status: Current status string (e.g. ``"proved"``, ``"failed"``).
        prover: Backend prover name (e.g. ``"zenon"``, ``"smt"``).
        meth: Method/timeout string, if provided.
        already: Whether the result came from the fingerprint cache.
        reason: Failure or interruption reason, if provided.
    """

    id: int
    loc: str
    status: str = TO_BE_PROVED
    prover: Optional[str] = None
    meth: Optional[str] = None
    already: Optional[bool] = None
    reason: Optional[str] = None
    obl: Optional[str] = None


@dataclass
class TLAPMRun:
    """Aggregated results from a single tlapm invocation.

    Attributes:
        started_at: Wall-clock start time.
        ended_at: Wall-clock end time.
        duration: Total elapsed time.
        success: ``True`` if all non-omitted obligations are proved.
        num_obligations: Total number of obligations (from final INFO line).
        obligations: Mapping from obligation id to :class:`TLAPMObligation`.
        errors: Plain-text error messages (non-toolbox format).
        warnings: Plain-text warning messages (non-toolbox format).
        log_file: Path to the raw tlapm output log, if saved.
    """

    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: Optional[timedelta] = None
    success: Optional[bool] = None
    num_obligations: int = 0
    obligations: dict[int, TLAPMObligation] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_file: Optional[Path] = None

    def to_dict(self) -> dict:
        """Convert this instance to a JSON-serialisable dictionary."""
        return asdict(self)

    @property
    def num_proved(self) -> int:
        return sum(1 for o in self.obligations.values() if o.status in _SUCCESS_STATUSES)

    @property
    def num_failed(self) -> int:
        return sum(1 for o in self.obligations.values() if o.status == FAILED)

    @property
    def num_pending(self) -> int:
        return sum(1 for o in self.obligations.values() if o.status not in _FINAL_STATUSES)

    @property
    def num_omitted(self) -> int:
        return sum(1 for o in self.obligations.values() if o.status == OMITTED)

    @property
    def num_interrupted(self) -> int:
        return sum(1 for o in self.obligations.values() if o.status == INTERRUPTED)

    @property
    def num_unproved(self) -> int:
        """Obligations that did not reach a proved/failed/omitted/interrupted verdict.

        Includes ``unknown`` results from tlapm and any obligations still pending
        when the run terminates (e.g. after a crash or timeout).
        """
        accounted = _SUCCESS_STATUSES | {FAILED, OMITTED, INTERRUPTED}
        seen = sum(1 for o in self.obligations.values() if o.status not in accounted)
        # The INFO line may report more obligations than tlapm emitted blocks for
        # (e.g. when the run is interrupted before all obligations are reported).
        if self.num_obligations > len(self.obligations):
            seen += self.num_obligations - len(self.obligations)
        return seen


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------


class TLAPMOutputParser:
    """Parses tlapm toolbox output (``--toolbox 0 0``) line-by-line.

    Lines between ``@!!BEGIN`` and ``@!!END`` are collected as blocks.
    Each block is parsed into its key-value fields and dispatched to the
    appropriate handler based on ``@!!type``.

    Feed lines via :meth:`feed_line`; call :meth:`populate_run` to
    transfer extracted data into a :class:`TLAPMRun`.
    """

    _RE_FIELD = re.compile(r"^@!!(\w+):(.*)")
    _RE_BEGIN = re.compile(r"^@!!BEGIN")
    _RE_END = re.compile(r"^@!!END")
    _RE_INFO_ALL = re.compile(r"\[INFO\].*?All\s+(\d+)\s+obligation")
    _RE_INFO_SOME = re.compile(r"\[INFO\].*?(\d+)\s+obligation.*?proved")

    def __init__(self) -> None:
        self._in_block: bool = False
        self._block_lines: list[str] = []
        self._current_key: Optional[str] = None
        self._current_value_lines: list[str] = []
        self._fields: dict[str, str] = {}

        self._obligations: dict[int, TLAPMObligation] = {}
        self._errors: list[str] = []
        self._warnings: list[str] = []
        self._num_obligations: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed_line(self, line: str) -> None:
        """Process one output line from tlapm."""
        if self._RE_BEGIN.match(line):
            self._in_block = True
            self._fields = {}
            self._current_key = None
            self._current_value_lines = []
            return

        if self._RE_END.match(line):
            if self._current_key is not None:
                self._flush_field()
            self._in_block = False
            self._dispatch_block(self._fields)
            return

        if self._in_block:
            m = self._RE_FIELD.match(line)
            if m:
                # Save current multi-line value
                if self._current_key is not None:
                    self._flush_field()
                self._current_key = m.group(1)
                self._current_value_lines = [m.group(2)]
            else:
                # Continuation of a multi-line value
                if self._current_key is not None:
                    self._current_value_lines.append(line)
            return

        # Outside blocks: look for the final summary line
        m = self._RE_INFO_ALL.search(line)
        if m:
            self._num_obligations = int(m.group(1))
            return

    def get_obligations(self) -> dict[int, TLAPMObligation]:
        return dict(self._obligations)

    def get_errors(self) -> list[str]:
        return list(self._errors)

    def get_warnings(self) -> list[str]:
        return list(self._warnings)

    def get_num_obligations(self) -> int:
        if self._num_obligations:
            return self._num_obligations
        return len(self._obligations)

    def populate_run(self, run: TLAPMRun) -> None:
        """Write all extracted data into *run*."""
        run.obligations = dict(self._obligations)
        run.errors = list(self._errors)
        run.warnings = list(self._warnings)
        if self._num_obligations:
            run.num_obligations = self._num_obligations
        else:
            run.num_obligations = len(self._obligations)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_field(self) -> None:
        if self._current_key is None:
            return
        value = "\n".join(self._current_value_lines).strip()
        self._fields[self._current_key] = value
        self._current_key = None
        self._current_value_lines = []

    def _dispatch_block(self, fields: dict[str, str]) -> None:
        block_type = fields.get("type", "")
        if block_type == "obligation":
            self._handle_obligation(fields)
        elif block_type == "warning":
            msg = fields.get("msg", "")
            if msg:
                self._warnings.append(msg)
        elif block_type == "error":
            msg = fields.get("msg", "")
            if msg:
                self._errors.append(msg)

    def _handle_obligation(self, fields: dict[str, str]) -> None:
        try:
            obl_id = int(fields["id"])
        except (KeyError, ValueError):
            return

        status = fields.get("status", TO_BE_PROVED)
        already_str = fields.get("already", "")
        already = already_str.lower() == "true" if already_str else None

        if obl_id in self._obligations:
            # Update existing obligation
            obl = self._obligations[obl_id]
            obl.status = status
            if "prover" in fields:
                obl.prover = fields["prover"] or None
            if "meth" in fields:
                obl.meth = fields["meth"] or None
            if already is not None:
                obl.already = already
            if "reason" in fields:
                obl.reason = fields["reason"] or None
            if "obl" in fields:
                obl.obl = fields["obl"] or None
        else:
            self._obligations[obl_id] = TLAPMObligation(
                id=obl_id,
                loc=fields.get("loc", ""),
                status=status,
                prover=fields.get("prover") or None,
                meth=fields.get("meth") or None,
                already=already,
                reason=fields.get("reason") or None,
                obl=fields.get("obl") or None,
            )


# ---------------------------------------------------------------------------
# Rich display
# ---------------------------------------------------------------------------


class TLAPMOutputDisplay:
    """Rich live display for a tlapm prover run.

    Used as a context manager: the live display is started on enter and
    stopped on exit.  Call :meth:`update` for each parsed line and
    :meth:`show_summary` once after the run completes.
    """

    def __init__(
        self,
        console: Console,
        module_name: str,
        *,
        interactive: bool = True,
        silent: bool = False,
        step_line: Optional[int] = None,
    ) -> None:
        self._console = console
        self._module_name = module_name
        self._interactive = interactive
        self._silent = silent
        self._step_line = step_line
        self._progress: Optional[Progress] = None
        self._live: Optional[Live] = None
        self._task_id: Optional[TaskID] = None
        self._last_proved: int = -1  # plain-mode state
        self._reported_failed_ids: set[int] = set()

    def __enter__(self) -> "TLAPMOutputDisplay":
        if not self._silent and self._interactive:
            self._progress = Progress(
                SpinnerColumn(),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=self._console,
                transient=False,
            )
            step_suffix = f" (line {self._step_line})" if self._step_line is not None else ""
            self._task_id = self._progress.add_task("", total=None)
            self._status_text = Text.from_markup(f"Proving {self._module_name}{step_suffix}…", overflow="fold")
            self._live = Live(
                self._make_renderable(),
                console=self._console,
                refresh_per_second=10,
                vertical_overflow="visible",
            )
            self._live.__enter__()
        return self

    def _make_renderable(self):
        return Group(self._status_text, self._progress)

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)
            self._live = None

    def update(self, parser: TLAPMOutputParser) -> None:
        """Refresh the display from *parser* state."""
        if self._silent:
            return

        obligations = parser.get_obligations()
        if not obligations:
            return

        total = parser.get_num_obligations() or len(obligations)
        proved = sum(1 for o in obligations.values() if o.status in _SUCCESS_STATUSES)
        failed = sum(1 for o in obligations.values() if o.status == FAILED)
        pending = sum(1 for o in obligations.values() if o.status not in _FINAL_STATUSES)

        # Report newly-failed obligations immediately as they arrive.
        newly_failed = sorted(
            (o for o in obligations.values() if o.status == FAILED and o.id not in self._reported_failed_ids),
            key=lambda o: _parse_loc(o.loc) or (0, 0, 0, 0),
        )
        for obl in newly_failed:
            self._reported_failed_ids.add(obl.id)
            loc_parts = _parse_loc(obl.loc)
            loc_str = f"line {loc_parts[0]}" if loc_parts else obl.loc
            prover_str = f" [{obl.prover}]" if obl.prover else ""
            reason_str = f" — {obl.reason[:80]}" if obl.reason else ""
            self._console.print(f"  [red]✗[/red] {loc_str}{prover_str}{reason_str}")

        if self._interactive:
            if self._progress is None or self._task_id is None:
                return
            step_suffix = f" (line {self._step_line})" if self._step_line is not None else ""
            parts: list[str] = [f"Proving {self._module_name}{step_suffix}"]
            parts.append(f"{proved}/{total} proved")
            if failed:
                parts.append(f"[red]{failed} failed[/red]")
            if pending:
                parts.append(f"{pending} in progress")
            description = " · ".join(parts)
            self._status_text = Text.from_markup(description, overflow="fold")
            self._progress.update(self._task_id, total=total, completed=proved)
            if self._live is not None:
                self._live.update(self._make_renderable())
        else:
            # Plain mode: print a line each time a new obligation is proved.
            if proved > self._last_proved:
                self._last_proved = proved
                failed_part = f", {failed} failed" if failed else ""
                self._console.print(f"[dim]{self._module_name}[/dim] · {proved}/{total} proved{failed_part}")

    def show_summary(self, run: TLAPMRun) -> None:
        """Print the final summary panel after the live display has closed.

        No-op when the display is in silent mode.
        """
        if self._silent:
            return
        proved = run.num_proved
        failed = run.num_failed
        total = run.num_obligations or len(run.obligations)
        duration_s = run.duration.total_seconds() if run.duration else 0

        if total == 0 and not run.success:
            error_messages = list(run.errors or []) + list(run.warnings or [])
            error_lines = [m.strip() for m in error_messages if m.strip()]
            if error_lines:
                body_text = "tlapm error:\n" + "\n".join(f"  {line}" for line in error_lines[:5])
            else:
                body_text = "tlapm exited with an error (no obligations were checked)"
            self._console.print(
                Panel(
                    Text(body_text, style="red"),
                    title=f"[bold]TLAPM · {self._module_name}[/bold]",
                    border_style="red",
                    expand=False,
                    padding=(0, 1),
                )
            )
            return

        omitted = run.num_omitted
        interrupted = run.num_interrupted
        unproved = run.num_unproved

        if run.success:
            lines: list[str] = [
                f"[green]✓[/green] All {proved} obligation(s) proved.",
            ]
            for label, count in (("omitted", omitted), ("interrupted", interrupted), ("unproved", unproved)):
                if count:
                    lines.append(f"  [yellow]{count} {label}[/yellow]")
            if run.warnings:
                lines.append(f"  [yellow]{len(run.warnings)} warning(s)[/yellow]")
            body = Text.from_markup("\n".join(lines))
            style = "green"
        else:
            lines = [f"[red]✗[/red] {failed}/{total} obligation(s) failed."]
            for label, count in (("omitted", omitted), ("interrupted", interrupted), ("unproved", unproved)):
                if count:
                    lines.append(f"  [yellow]{count} {label}[/yellow]")
            failed_obls = sorted(
                (o for o in run.obligations.values() if o.status == FAILED),
                key=lambda o: _parse_loc(o.loc) or (0, 0, 0, 0),
            )
            for obl in failed_obls[:10]:
                loc_parts = _parse_loc(obl.loc)
                loc_str = f"line {loc_parts[0]}" if loc_parts else obl.loc
                prover_str = f" [dim][{obl.prover}][/dim]" if obl.prover else ""
                reason_str = f" — {obl.reason}" if obl.reason else ""
                lines.append(f"  [red]•[/red] {loc_str}{prover_str}{reason_str}")
                if obl.obl:
                    for obl_line in obl.obl.strip().splitlines():
                        lines.append(f"    [dim]{escape(obl_line)}[/dim]")
            if len(failed_obls) > 10:
                lines.append(f"  … and {len(failed_obls) - 10} more")
            for err in run.errors[:3]:
                lines.append(f"  [red]{escape(err)}[/red]")
            if len(run.errors) > 3:
                lines.append(f"  … and {len(run.errors) - 3} more error(s)")
            body = Text.from_markup("\n".join(lines))
            style = "red"

        duration_str = f"{duration_s:.1f}s" if duration_s else ""
        title_suffix = f" ({duration_str})" if duration_str else ""
        self._console.print(
            Panel(
                body,
                title=f"[bold]TLAPM · {self._module_name}{title_suffix}[/bold]",
                border_style=style,
                expand=False,
                padding=(0, 1),
            )
        )


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------


class TLAPM(Tool):
    """Tool for running the TLAPS prover (``tlapm``).

    Invokes the ``tlapm`` binary with ``--toolbox 0 0`` so that proof
    obligation updates are emitted in the structured toolbox protocol.
    Output is fed through :class:`TLAPMOutputParser` line-by-line and a
    Rich live display shows progress.

    Attributes:
        binary_path: Absolute path to the ``tlapm`` executable.
        community_modules_dir: Directory containing CommunityModules
            ``.tla`` files, added via ``-I`` when requested.
    """

    def __init__(
        self,
        binary_path: Path,
        community_modules_dir: Path,
        logger: Logger,
        console: Console,
    ) -> None:
        super().__init__("tlapm", logger, console)
        self.binary_path = binary_path
        self.community_modules_dir = community_modules_dir

    def is_available(self) -> bool:
        return self.binary_path.exists()

    def prove(
        self,
        module_path: Path,
        *,
        stretch: Optional[float] = None,
        community_modules: bool = False,
        include_dirs: Optional[list[Path]] = None,
        timeout: Optional[timedelta] = None,
        interactive: bool = True,
        silent: bool = False,
        cache_dir: Optional[Path] = None,
        nofp: bool = False,
        cleanfp: bool = False,
        step_line: Optional[int] = None,
    ) -> TLAPMRun:
        """Run tlapm on *module_path* and return the results.

        Args:
            module_path: Absolute path to the TLA+ proof file.
            stretch: Multiply all backend timeouts by this factor
                (``--stretch``).
            community_modules: If ``True``, add the CommunityModules
                directory to tlapm's search path (``-I``).
            include_dirs: Additional directories added to tlapm's module
                search path (``-I``).  Pass the parent of a ``.tla`` file to
                make that file discoverable.
            timeout: If provided, kill tlapm after this duration.

        Returns:
            A populated :class:`TLAPMRun`.
        """
        run = TLAPMRun(started_at=datetime.now())

        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

        cmd = [str(self.binary_path), "--toolbox", "0", "0"]
        if stretch is not None:
            cmd.extend(["--stretch", str(stretch)])
        if nofp:
            cmd.append("--nofp")
        if cleanfp:
            cmd.append("--cleanfp")
        if step_line is not None:
            cmd.extend(["--line", str(step_line)])
        if community_modules and self.community_modules_dir.exists():
            cmd.extend(["-I", str(self.community_modules_dir)])
        for d in include_dirs or []:
            cmd.extend(["-I", str(d)])
        cmd.append(str(module_path))

        env = {**os.environ, "TLAPM_CACHE_DIR": str(cache_dir)} if cache_dir is not None else None

        output_lines: list[str] = []
        parser = TLAPMOutputParser()
        display = TLAPMOutputDisplay(self.console, module_path.stem, interactive=interactive, silent=silent, step_line=step_line)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        if process.stdout is None:
            raise RuntimeError("Failed to launch tlapm: no stdout pipe.")

        # Optional timeout: kill process after deadline
        timer: Optional[threading.Timer] = None
        if timeout is not None:

            def _kill():
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

            timer = threading.Timer(timeout.total_seconds(), _kill)
            timer.daemon = True
            timer.start()

        try:
            with display:
                for line in process.stdout:
                    stripped = line.rstrip("\n")
                    parser.feed_line(stripped)
                    display.update(parser)
                    output_lines.append(line)
                process.wait()
        finally:
            if timer is not None:
                timer.cancel()

        run.ended_at = datetime.now()
        run.duration = run.ended_at - run.started_at
        parser.populate_run(run)

        # Determine success: no failed obligations and process exited cleanly
        failed = sum(1 for o in run.obligations.values() if o.status == FAILED)
        run.success = (process.returncode == 0) and (failed == 0)

        if cache_dir is not None:
            run.log_file = cache_dir / "tlapm.log"
            run.log_file.write_text("".join(output_lines))

        display.show_summary(run)
        return run
