"""TLC model checker wrapper.

This module exposes the :class:`TLC` tool class that builds and executes the
TLC model checker as a subprocess, as well as the :class:`TLCRun` dataclass
that stores all data produced by a single run.
"""

import json
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from logging import Logger
from pathlib import Path
from typing import Any, Optional, Union

from rich.console import Console

from .java import JavaClassTool
from .tlc_output import (
    TLCActionCoverage,
    TLCDiagnostic,
    TLCOutputDisplay,
    TLCOutputParser,
    TLCProgress,
    TLCTraceState,
)


@dataclass
class TLCRun:
    """Data class storing the results and metadata of a single TLC run.

    Attributes:
        started_at: Wall-clock time when the run was started.
        ended_at: Wall-clock time when the run ended.
        duration: Total elapsed time of the run.
        tlc_version: TLC version string (e.g. ``"2.19"``).
        tlc_rev: TLC git revision hash.
        seed: Fingerprint seed used for this run.
        num_workers: Number of TLC worker threads.
        num_cores: Number of CPU cores available as reported by TLC.
        heap_size: JVM heap size in MB.
        offheap_size: JVM off-heap size in MB.
        mode: Running mode string (e.g. ``"breadth-first search Model-Checking"``).
        modules: Ordered list of ``.tla`` file paths parsed during the run.
        loads: Mapping of module names to load timestamps (reserved for future use).
        success: ``True`` if no error was found, ``False`` otherwise.
        total_states: Total number of states generated.
        total_distinct_states: Number of distinct states found.
        num_states_queued: Number of states left on the queue when TLC finished.
        state_depth: Depth of the complete state-graph search.
        error_type: Human-readable error category (e.g. ``"Safety failure"``).
        error_msg: Error message extracted from TLC output.
        log_file: Path to the raw TLC output log saved on disk.
        states_file: Path to the exported state-space file (if requested).
        ttrace_spec: Path to the TTrace specification generated on violation.
        coverage: Per-action coverage statistics collected with ``-coverage``.
        progress_history: All progress snapshots emitted during the run.
        checkpoint_dir: Metadata directory used for checkpointing, if any.
        diagnostics: Semantic/parsing error diagnostics (semantic_error kind).
        error_kind: Classified error kind (e.g. ``"deadlock"``, ``"safety_violation"``).
        trace: Ordered list of states in the error trace (property violations).
    """

    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: Optional[timedelta] = None
    tlc_version: Optional[str] = None
    tlc_rev: Optional[str] = None
    seed: Optional[int] = None
    num_workers: Optional[int] = None
    num_cores: Optional[int] = None
    heap_size: Optional[int] = None
    offheap_size: Optional[int] = None
    mode: Optional[str] = None
    modules: Optional[list[str]] = None
    loads: Optional[dict[str, str]] = None
    success: Optional[bool] = None
    total_states: Optional[int] = None
    total_distinct_states: Optional[int] = None
    num_states_queued: Optional[int] = None
    state_depth: Optional[int] = None
    error_type: Optional[str] = None
    error_msg: Optional[str] = None
    log_file: Optional[Path] = None
    states_file: Optional[Path] = None
    ttrace_spec: Optional[Path] = None
    coverage: Optional[list[TLCActionCoverage]] = None
    progress_history: Optional[list[TLCProgress]] = None
    checkpoint_dir: Optional[Path] = None
    diagnostics: Optional[list[TLCDiagnostic]] = None
    error_kind: Optional[str] = None
    trace: Optional[list[TLCTraceState]] = None
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert this instance to a JSON-serialisable dictionary."""
        return asdict(self)


class TLC(JavaClassTool):
    """Tool for running the TLC model checker.

    Wraps the ``tlc2.TLC`` Java class, builds the appropriate JVM command,
    streams output through :class:`~cli.tools.tlc_output.TLCOutputParser` and
    :class:`~cli.tools.tlc_output.TLCOutputDisplay`, and returns a fully
    populated :class:`TLCRun`.

    Class Attributes:
        tlc_exit_codes: Mapping of TLC exit codes to human-readable error types.

    Attributes:
        base_path: Root directory under which per-run data directories are created.
        community_modules: Package providing the CommunityModules JAR.
    """

    tlc_exit_codes: dict[int, str] = {
        0: "Success",
        1: "Error",
        10: "Assumption failure",
        11: "Deadlock failure",
        12: "Safety failure",
        13: "Liveness failure",
    }

    def __init__(
        self,
        main_class: str,
        tla2tools_jar: Path,
        community_modules_jar: Path,
        stdlib_dir: Path,
        logger: Logger,
        console: Console,
    ) -> None:
        super().__init__(
            name="TLC",
            classpath=tla2tools_jar,
            main_class=main_class,
            logger=logger,
            console=console,
        )
        self.community_modules_jar = community_modules_jar
        self.stdlib_dir = stdlib_dir

    def _build_extra_classpath(
        self,
        community_modules: bool,
        tlaps_stdlib: bool,
        external_modules: list[Path],
    ) -> list[Path]:
        """Assemble the per-invocation classpath additions.

        Args:
            community_modules: Whether to include the CommunityModules JAR.
            tlaps_stdlib: Whether to include the TLAPS stdlib directory.
            external_modules: Additional JAR files or directories.

        Returns:
            List of extra :class:`~pathlib.Path` entries to pass as
            *extra_classpath* to :meth:`~JavaClassTool.get_java_command`.
        """
        extra: list[Path] = []
        if community_modules and self.community_modules_jar.exists():
            extra.append(self.community_modules_jar)
        if tlaps_stdlib and self.stdlib_dir.exists():
            extra.append(self.stdlib_dir)
        extra.extend(external_modules)
        return extra

    def start(
        self,
        module_path: Path,
        model_path: Path,
        *,
        workers: Union[int, str] = 1,
        max_heap_size: str,
        community_modules: bool,
        tlaps_stdlib: bool = False,
        external_modules: list[Path],
        save_states: bool = False,
        export_json: bool = False,
        checkpoint_dir: Optional[Path] = None,
        checkpoint_interval: Optional[int] = None,
        coverage_interval: Optional[int] = None,
        timeout: Optional[timedelta] = None,
        show_log: bool = False,
        interactive: bool = True,
        silent: bool = False,
        cache_dir: Optional[Path] = None,
        no_deadlock: bool = False,
        continue_after_error: bool = False,
        difftrace: bool = False,
    ) -> TLCRun:
        """Run TLC in exhaustive model-checking mode and return the results.

        Args:
            module_path: Path to the TLA+ module file (``.tla``).
            model_path: Path to the TLC model configuration file (``.cfg``).
            workers: Number of TLC worker threads (``-workers N``).
            max_heap_size: Maximum JVM heap size (e.g. ``"4G"``).
            community_modules: Whether to add the CommunityModules JAR to the
                classpath.
            external_modules: Additional JAR files or directories to add to the
                classpath.
            save_states: If ``True``, export the state space as a Graphviz
                ``.dot`` file (``-dump dot states``).
            export_json: If ``True``, export the state space as a JSON file
                (``-dump json states``).
            checkpoint_dir: Directory used by TLC for metadata and checkpoints
                (``-metadir``).
            checkpoint_interval: Checkpoint interval in minutes (``-checkpoint N``).
            coverage_interval: Report action-coverage statistics every *N*
                minutes (``-coverage N``).  Use ``0`` to report once at the end.
            timeout: If provided, kill TLC after this duration.
            show_log: If ``True``, also print raw TLC output lines to the console.

        Returns:
            A fully populated :class:`TLCRun` describing the run results.
        """
        if cache_dir is not None:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True)
        run_dir = cache_dir or module_path.parent
        tlc_run = TLCRun(started_at=datetime.now())

        tlc_args = ["-workers", str(workers), "-config", str(model_path)]

        if cache_dir is not None:
            tlc_args.extend(["-teSpecOutDir", str(cache_dir)])

        if save_states:
            tlc_run.states_file = run_dir / "states.dot"
            tlc_args.extend(["-dump", "dot", str(tlc_run.states_file)])

        if export_json:
            trace_file = run_dir / "trace"   # TLC appends .json automatically
            tlc_args.extend(["-dumpTrace", "json", str(trace_file)])
            tlc_run.states_file = run_dir / "trace.json"

        if checkpoint_dir is not None:
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            tlc_args.extend(["-metadir", str(checkpoint_dir)])
            tlc_run.checkpoint_dir = checkpoint_dir
        if checkpoint_interval is not None:
            tlc_args.extend(["-checkpoint", str(checkpoint_interval)])

        if coverage_interval is not None:
            tlc_args.extend(["-coverage", str(coverage_interval)])

        if no_deadlock:
            tlc_args.append("-deadlock")
        if continue_after_error:
            tlc_args.append("-continue")
        if difftrace:
            tlc_args.append("-difftrace")

        tlc_args.append(str(module_path))

        extra_cp = self._build_extra_classpath(community_modules, tlaps_stdlib, external_modules)
        cmd = self.get_java_command(
            tlc_args,
            extra_classpath=extra_cp,
            max_heap_size=max_heap_size,
            parallel_gc=True,
        )

        tlc_output, process, display = self._run_process(
            cmd,
            run_dir,
            module_path.stem,
            tlc_run,
            show_log,
            timeout=timeout,
            interactive=interactive,
            silent=silent,
        )

        if process.returncode == 0:
            self._parse_success(tlc_run, tlc_output)
        else:
            self._parse_failure(tlc_run, tlc_output, process.returncode)

        self._save_run_data(tlc_run, cache_dir, tlc_output)
        display.show_summary(tlc_run, cache_dir)
        return tlc_run

    def simulate(
        self,
        module_path: Path,
        model_path: Path,
        *,
        workers: Union[int, str] = 1,
        max_heap_size: str,
        community_modules: bool,
        tlaps_stdlib: bool = False,
        external_modules: list[Path],
        depth: Optional[int] = None,
        seed: Optional[int] = None,
        num_traces: Optional[int] = None,
        timeout: Optional[timedelta] = None,
        show_log: bool = False,
        interactive: bool = True,
        silent: bool = False,
        cache_dir: Optional[Path] = None,
        no_deadlock: bool = False,
        continue_after_error: bool = False,
        difftrace: bool = False,
    ) -> TLCRun:
        """Run TLC in simulation mode and return the results.

        In simulation mode TLC performs random depth-first trace exploration
        rather than exhaustive breadth-first state-space search.

        Args:
            module_path: Path to the TLA+ module file (``.tla``).
            model_path: Path to the TLC model configuration file (``.cfg``).
            workers: Number of parallel simulation workers (``-workers N``).
            max_heap_size: Maximum JVM heap size (e.g. ``"4G"``).
            community_modules: Whether to add the CommunityModules JAR to the
                classpath.
            external_modules: Additional JAR files or directories to add to the
                classpath.
            depth: Maximum depth of each simulated trace (``-depth N``).
            seed: Random seed for reproducible simulation (``-seed N``).
            num_traces: Number of traces to simulate before stopping
                (``-numTraces N``).  By default TLC simulates indefinitely.
            show_log: If ``True``, also print raw TLC output lines to the console.

        Returns:
            A :class:`TLCRun` describing the simulation results.
        """
        if cache_dir is not None:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True)
        run_dir = cache_dir or module_path.parent
        tlc_run = TLCRun(started_at=datetime.now())

        simulate_arg = ["-simulate"]
        if num_traces is not None:
            simulate_arg.append(f"num={num_traces}")
        tlc_args = simulate_arg + ["-workers", str(workers), "-config", str(model_path)]

        if cache_dir is not None:
            tlc_args.extend(["-teSpecOutDir", str(cache_dir)])

        if depth is not None:
            tlc_args.extend(["-depth", str(depth)])
        if seed is not None:
            tlc_args.extend(["-seed", str(seed)])

        if no_deadlock:
            tlc_args.append("-deadlock")
        if continue_after_error:
            tlc_args.append("-continue")
        if difftrace:
            tlc_args.append("-difftrace")

        tlc_args.append(str(module_path))

        extra_cp = self._build_extra_classpath(community_modules, tlaps_stdlib, external_modules)
        cmd = self.get_java_command(
            tlc_args,
            extra_classpath=extra_cp,
            max_heap_size=max_heap_size,
            parallel_gc=True,
        )

        tlc_output, process, display = self._run_process(
            cmd,
            run_dir,
            module_path.stem,
            tlc_run,
            show_log,
            timeout=timeout,
            interactive=interactive,
            silent=silent,
        )

        if process.returncode == 0:
            self._parse_success(tlc_run, tlc_output)
        else:
            self._parse_failure(tlc_run, tlc_output, process.returncode)

        self._save_run_data(tlc_run, cache_dir, tlc_output)
        display.show_summary(tlc_run, cache_dir)
        return tlc_run

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_process(
        self,
        cmd: list[str],
        run_dir: Path,
        module_name: str,
        tlc_run: TLCRun,
        show_log: bool,
        timeout: Optional[timedelta] = None,
        interactive: bool = True,
        silent: bool = False,
    ) -> tuple[str, subprocess.Popen, TLCOutputDisplay]:
        """Launch the TLC subprocess, stream output through the display, and wait.

        Args:
            cmd: Full Java command-line as a list of strings.
            run_dir: Working directory for the subprocess.
            module_name: Short module name used in the display title.
            tlc_run: :class:`TLCRun` instance to populate via the parser.
            show_log: If ``True``, each raw output line is also printed.
            timeout: If provided, kill TLC after this duration.

        Returns:
            A tuple of ``(raw_output_string, completed_Popen_instance, display)``.
        """
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=run_dir,
            text=True,
        )

        if process.stdout is None:
            raise RuntimeError("Failed to launch TLC: no stdout pipe.")

        parser = TLCOutputParser()
        tlc_output_lines: list[str] = []
        display = TLCOutputDisplay(self.console, module_name, interactive=interactive, silent=silent)

        timer: Optional[threading.Timer] = None
        if timeout is not None:

            def _kill():
                try:
                    process.kill()
                    run.timed_out = True
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
                    if show_log:
                        self.console.print(stripped)
                    tlc_output_lines.append(line)
        finally:
            if timer is not None:
                timer.cancel()

        process.wait()

        tlc_run.ended_at = datetime.now()
        tlc_run.duration = tlc_run.ended_at - tlc_run.started_at
        parser.populate_run(tlc_run)

        return "".join(tlc_output_lines), process, display

    def _parse_success(self, tlc_run: TLCRun, output: str) -> None:
        """Mark a :class:`TLCRun` as successful after exit code 0."""
        tlc_run.success = True

    def _parse_failure(self, tlc_run: TLCRun, output: str, code: int) -> None:
        """Finalise a :class:`TLCRun` after a failed TLC run.

        Sets ``error_type`` from the exit code and fills in ``error_kind`` for
        runtime violations when the parser has not already classified the error.

        Exit-code-to-kind mapping:

        - ``10`` → ``"assumption_violation"``
        - ``11`` → ``"deadlock"``
        - ``12`` → ``"safety_violation"``
        - ``13`` → ``"liveness_violation"``
        - ``1``  → ``"runtime_error"``
        - other  → ``"unknown"``
        """
        tlc_run.success = False

        if tlc_run.timed_out:
            tlc_run.error_type = "Timeout"
            tlc_run.error_kind = "timeout"
            return

        if code in self.tlc_exit_codes:
            tlc_run.error_type = self.tlc_exit_codes[code]
        elif tlc_run.error_msg is not None:
            tlc_run.error_type = "Error"
        else:
            tlc_run.error_type = f"Unknown error (exit {code})"

        if tlc_run.error_kind is None:
            _exit_kind: dict[int, str] = {
                10: "assumption_violation",
                11: "deadlock",
                12: "safety_violation",
                13: "liveness_violation",
                1: "runtime_error",
            }
            tlc_run.error_kind = _exit_kind.get(code, "unknown")

        if tlc_run.error_msg is None and tlc_run.error_kind not in ("config_not_found", "semantic_error") and "Error:" in output:
            tlc_run.error_msg = output.split("Error:")[-1].strip()

    def _save_run_data(self, tlc_run: TLCRun, run_dir: Optional[Path], output: str) -> None:
        """Persist the raw TLC log and a JSON summary of the run to *run_dir*.

        Creates ``tlc.log`` (verbatim output) and ``run-data.json``.
        No-op when *run_dir* is ``None``.
        """
        if run_dir is None:
            return
        tlc_run.log_file = run_dir / "tlc.log"
        with tlc_run.log_file.open("w") as f:
            f.write(output)
        with (run_dir / "run-data.json").open("w") as f:
            json.dump(tlc_run.to_dict(), f, indent=4, default=str)
