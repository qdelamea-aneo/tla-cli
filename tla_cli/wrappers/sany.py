"""SANY parser wrapper.

This module wraps the ``tla2sany.SANY`` Java class from tla2tools.jar and
provides a structured interface to parse and type-check TLA+ source files.

Classes:
    SANYRun: Dataclass holding the result of a SANY run.
    SANYOutputParser: Parses SANY stdout line-by-line into structured data.
    SANYOutputDisplay: Rich live terminal display for SANY runs.
    SANY: Tool class that builds and executes the SANY parser.
"""

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from logging import Logger
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from .java import JavaClassTool

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SANYDiagnostic:
    """A single error or warning emitted by SANY.

    Attributes:
        severity: Either ``"error"`` or ``"warning"``.
        message: The diagnostic message text.
        module: Name of the module the diagnostic refers to, if known.
    """

    severity: str
    message: str
    module: Optional[str] = None


@dataclass
class SANYRun:
    """Results from a single SANY parse-and-type-check run.

    Attributes:
        started_at: Wall-clock start time.
        ended_at: Wall-clock end time.
        duration: Total elapsed time.
        success: ``True`` if SANY exited successfully (exit 0).
        modules_parsed: Ordered list of ``.tla`` file paths parsed.
        modules_semantic: Modules that passed semantic analysis.
        errors: Structured error diagnostics.
        warnings: Structured warning diagnostics.
        log_file: Path to the raw SANY output log, if saved.
    """

    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: Optional[timedelta] = None
    success: Optional[bool] = None
    modules_parsed: list[str] = field(default_factory=list)
    modules_semantic: list[str] = field(default_factory=list)
    errors: list[SANYDiagnostic] = field(default_factory=list)
    warnings: list[SANYDiagnostic] = field(default_factory=list)
    log_file: Optional[Path] = None

    def to_dict(self) -> dict:
        """Convert this instance to a JSON-serialisable dictionary."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------


class SANYOutputParser:
    """Parses SANY output line-by-line into a :class:`SANYRun`.

    Feed lines via :meth:`feed_line`; retrieve results via
    :meth:`populate_run` once the process exits.
    """

    _RE_PARSING = re.compile(r"^Parsing file (.+\.tla)")
    _RE_SEMANTIC = re.compile(r"^Semantic processing of module (\w+)")
    _RE_PARSE_EXCEPTION = re.compile(r"^SANY\d* Parse Exception")
    _RE_FATAL = re.compile(r"^Fatal errors")
    _RE_ERRORS = re.compile(r"\*\*\* Errors?:?\s*(\d+)")
    _RE_ABORT = re.compile(r"^Abort messages were encountered")

    def __init__(self) -> None:
        self._modules_parsed: list[str] = []
        self._modules_semantic: list[str] = []
        self._errors: list[SANYDiagnostic] = []
        self._error_accumulator: list[str] = []
        self._in_error_block: bool = False
        self._has_errors: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed_line(self, line: str) -> None:
        """Process one output line from SANY."""
        m = self._RE_PARSING.match(line)
        if m:
            self._flush_error()
            self._modules_parsed.append(m.group(1))
            return

        m = self._RE_SEMANTIC.match(line)
        if m:
            self._flush_error()
            self._modules_semantic.append(m.group(1))
            return

        if self._RE_PARSE_EXCEPTION.match(line) or self._RE_FATAL.match(line):
            self._flush_error()
            self._in_error_block = True
            return

        m = self._RE_ERRORS.search(line)
        if m:
            count = int(m.group(1))
            if count > 0:
                self._has_errors = True
            if not self._in_error_block and count > 0:
                # Semantic errors: location + message follow this line.
                self._flush_error()
                self._in_error_block = True
            else:
                # Parse exception: content came before this line; just flush.
                self._flush_error()
            return

        if self._RE_ABORT.match(line):
            self._flush_error()
            return

        # Accumulate free-form error text
        if self._in_error_block and line.strip():
            self._error_accumulator.append(line)

    def get_modules_parsed(self) -> list[str]:
        return list(self._modules_parsed)

    def get_modules_semantic(self) -> list[str]:
        return list(self._modules_semantic)

    def get_errors(self) -> list[SANYDiagnostic]:
        self._flush_error()
        return list(self._errors)

    def has_errors(self) -> bool:
        """Return True if any errors were detected, whether or not their text was captured."""
        self._flush_error()
        return self._has_errors or len(self._errors) > 0

    def populate_run(self, run: SANYRun) -> None:
        """Write all extracted data into *run*."""
        self._flush_error()
        run.modules_parsed = list(self._modules_parsed)
        run.modules_semantic = list(self._modules_semantic)
        run.errors = list(self._errors)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush_error(self) -> None:
        if self._error_accumulator:
            msg = "\n".join(self._error_accumulator).strip()
            if msg:
                self._errors.append(SANYDiagnostic(severity="error", message=msg))
            self._error_accumulator.clear()
        self._in_error_block = False


# ---------------------------------------------------------------------------
# Rich display
# ---------------------------------------------------------------------------


class SANYOutputDisplay:
    """Rich live display for a SANY run.

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
    ) -> None:
        self._console = console
        self._module_name = module_name
        self._interactive = interactive
        self._silent = silent
        self._live: Optional[Live] = None
        self._last_module_count: int = 0  # plain-mode state

    def __enter__(self) -> "SANYOutputDisplay":
        if not self._silent and self._interactive:
            self._live = Live(
                self._render(None),
                console=self._console,
                refresh_per_second=10,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)
            self._live = None

    def update(self, parser: SANYOutputParser) -> None:
        """Refresh the display from *parser* state."""
        if self._silent:
            return
        if self._interactive:
            if self._live:
                self._live.update(self._render(parser))
        else:
            # Plain mode: print a line each time a new module appears.
            semantic = parser.get_modules_semantic()
            parsed = parser.get_modules_parsed()
            current = len(semantic) if semantic else len(parsed)
            if current > self._last_module_count:
                self._last_module_count = current
                if semantic:
                    self._console.print(f"[dim]{self._module_name}[/dim] · Semantic analysis: {len(semantic)} module(s)")
                elif parsed:
                    from pathlib import Path as _Path

                    self._console.print(f"[dim]{self._module_name}[/dim] · Parsing: {_Path(parsed[-1]).name}")

    def show_summary(self, run: SANYRun) -> None:
        """Print the final summary panel after the live display has closed.

        No-op when the display is in silent mode.
        """
        if self._silent:
            return
        if run.success:
            modules = run.modules_semantic or run.modules_parsed
            body = Text.assemble(
                ("[green]✓[/green] ", ""),
                (f"Parsed {len(modules)} module(s) successfully.", ""),
            )
        else:
            body_lines: list[Text] = []
            body_lines.append(
                Text.assemble(
                    ("[red]✗[/red] ", ""),
                    ("SANY reported errors:", "bold red"),
                )
            )
            for diag in run.errors[:5]:
                body_lines.append(Text(f"  {diag.message[:120]}", style="red"))
            if len(run.errors) > 5:
                body_lines.append(Text(f"  … and {len(run.errors) - 5} more", style="dim"))
            body = Text("\n").join(body_lines)

        style = "green" if run.success else "red"
        self._console.print(
            Panel(
                body,
                title=f"[bold]SANY · {self._module_name}[/bold]",
                border_style=style,
                expand=False,
                padding=(0, 1),
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render(self, parser: Optional[SANYOutputParser]) -> Spinner:
        if parser is None:
            msg = f"Parsing {self._module_name}…"
        else:
            modules = parser.get_modules_parsed()
            semantic = parser.get_modules_semantic()
            if semantic:
                msg = f"Semantic analysis — {len(semantic)} module(s)"
            elif modules:
                last = Path(modules[-1]).name if modules else ""
                msg = f"Parsing… {last}"
            else:
                msg = f"Parsing {self._module_name}…"
        return Spinner("dots", text=msg)


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------


class SANY(JavaClassTool):
    """Tool for running the SANY TLA+ parser and type-checker.

    Wraps the ``tla2sany.SANY`` Java main class from tla2tools.jar,
    feeds stdout through :class:`SANYOutputParser`, and renders a Rich
    live display while parsing.

    Attributes:
        community_modules: Package providing the CommunityModules JAR
            (added to the classpath when requested).
        data_path: Base directory under which per-run log directories are
            created.  When ``None``, no log file is saved.
    """

    def __init__(
        self,
        tla2tools_jar: Path,
        community_modules_jar: Path,
        stdlib_dir: Path,
        logger: Logger,
        console: Console,
    ) -> None:
        super().__init__(
            name="SANY",
            classpath=tla2tools_jar,
            main_class="tla2sany.SANY",
            logger=logger,
            console=console,
        )
        self.community_modules_jar = community_modules_jar
        self.stdlib_dir = stdlib_dir

    def parse(
        self,
        module_path: Path,
        *,
        community_modules: bool = False,
        tlaps_stdlib: bool = False,
        external_modules: Optional[list[Path]] = None,
        interactive: bool = True,
        silent: bool = False,
        cache_dir: Optional[Path] = None,
    ) -> SANYRun:
        """Run SANY on *module_path* and return the results.

        Args:
            module_path: Absolute path to the TLA+ source file.
            community_modules: If ``True``, add the CommunityModules JAR
                to the Java classpath.
            external_modules: Additional JAR files or directories to add
                to the classpath.

        Returns:
            A populated :class:`SANYRun`.
        """
        if external_modules is None:
            external_modules = []

        run = SANYRun(started_at=datetime.now())

        extra_cp: list[Path] = []
        if community_modules and self.community_modules_jar.exists():
            extra_cp.append(self.community_modules_jar)
        if tlaps_stdlib and self.stdlib_dir.exists():
            extra_cp.append(self.stdlib_dir)
        extra_cp.extend(external_modules)

        # Pass just the filename; SANY is launched with cwd=module_path.parent
        # so sibling .tla files are found automatically.
        cmd = self.get_java_command([module_path.name], extra_classpath=extra_cp)
        output_lines: list[str] = []
        parser = SANYOutputParser()
        display = SANYOutputDisplay(self.console, module_path.stem, interactive=interactive, silent=silent)

        with display:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=module_path.parent,
                text=True,
            )
            if process.stdout is None:
                raise RuntimeError("Failed to launch SANY: no stdout pipe.")
            for line in process.stdout:
                stripped = line.rstrip("\n")
                parser.feed_line(stripped)
                display.update(parser)
                output_lines.append(line)
            process.wait()

        run.ended_at = datetime.now()
        run.duration = run.ended_at - run.started_at
        parser.populate_run(run)
        run.success = process.returncode == 0 and not parser.has_errors()

        if cache_dir is not None:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True)
            run.log_file = cache_dir / "sany.log"
            run.log_file.write_text("".join(output_lines))

        display.show_summary(run)
        return run
