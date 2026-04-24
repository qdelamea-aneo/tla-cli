"""Shared parse/semantic diagnostics used by both SANY and TLC output parsers.

SANY emits the same diagnostic formats whether invoked standalone by ``tla
parse`` or indirectly by TLC during its preprocessing phase.  This module
centralises the regex patterns used to recognise those formats and provides a
single Rich renderer so both ``tla parse`` and ``tla mc`` display errors with
identical structure.
"""

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from rich.table import Table

ParseDiagnosticKind = Literal["syntax", "missing_module", "semantic", "fatal"]


@dataclass
class ParseDiagnostic:
    """A structured SANY-level diagnostic.

    Attributes:
        kind: Category of diagnostic (syntax/missing module/semantic/fatal).
        message: Human-readable message (without location — location lives in
            dedicated fields).
        module: Module where the error was detected.
        line: First line of the offending source range.
        col: First column of the offending source range.
        line_end: Last line (inclusive); defaults to ``line`` when equal.
        col_end: Last column (inclusive).
        token: The specific token reported by the parser for syntax errors.
        severity: ``"error"`` or ``"warning"``.
    """

    kind: ParseDiagnosticKind
    message: str
    module: Optional[str] = None
    line: Optional[int] = None
    col: Optional[int] = None
    line_end: Optional[int] = None
    col_end: Optional[int] = None
    token: Optional[str] = None
    severity: Literal["error", "warning"] = "error"

    def dedup_key(self) -> tuple:
        return (self.kind, self.module, self.line, self.col, self.message)


@dataclass
class DiagnosticSet:
    """Accumulator for :class:`ParseDiagnostic` objects with deduplication.

    SANY and TLC frequently repeat the same diagnostic twice (once per
    dependent module).  Callers push diagnostics here instead of a raw list to
    get dedup for free.
    """

    diagnostics: list[ParseDiagnostic] = field(default_factory=list)
    _seen: set[tuple] = field(default_factory=set, repr=False)

    def add(self, diag: ParseDiagnostic) -> bool:
        """Add *diag* if not already present. Returns ``True`` if added."""
        key = diag.dedup_key()
        if key in self._seen:
            return False
        self._seen.add(key)
        self.diagnostics.append(diag)
        return True

    def __bool__(self) -> bool:
        return bool(self.diagnostics)

    def __len__(self) -> int:
        return len(self.diagnostics)

    def __iter__(self):
        return iter(self.diagnostics)


# ---------------------------------------------------------------------------
# Regex patterns — single source of truth, shared by both wrappers
# ---------------------------------------------------------------------------

# "***Parse Error***" — SANY's syntax-error banner (one line).
RE_PARSE_ERROR_HEADER = re.compile(r"^\*\*\*Parse Error\*\*\*")

# 'Encountered "X" at line N, column M and token "Y"'
# The trailing 'and token "..."' portion is optional for robustness.
RE_ENCOUNTERED = re.compile(
    r'Encountered "(?P<expect>[^"]+)" at line (?P<line>\d+), column (?P<col>\d+)'
    r'(?: and token "(?P<tok>[^"]*)")?'
)

# 'Cannot find source file for module X imported in module Y.'
RE_CANNOT_FIND = re.compile(r"^Cannot find source file for module (?P<missing>\w+) imported in module (?P<parent>\w+)\.?\s*$")

# 'Could not parse module X from file Y'
RE_COULD_NOT_PARSE = re.compile(r"^Could not parse module (?P<mod>\w+) from file")

# 'line Ls, col Cs to line Le, col Ce of module M' — semantic error location.
RE_SEMANTIC_LOC = re.compile(r"^line (?P<ls>\d+), col (?P<cs>\d+) to line (?P<le>\d+), col (?P<ce>\d+) of module (?P<mod>\w+)")


def render_parse_diagnostics(
    diagnostics: "list[ParseDiagnostic] | DiagnosticSet",
    *,
    title: Optional[str] = None,
) -> Table:
    """Render a list of :class:`ParseDiagnostic` as a Rich table.

    Columns: Module, Location (``—`` when no source range), Kind, Message.
    """
    table = Table(title=title, show_header=True, header_style="bold", show_lines=True, expand=False)
    table.add_column("Module", style="cyan", no_wrap=True)
    table.add_column("Location", style="dim", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Message")

    _KIND_LABELS = {
        "syntax": "Syntax",
        "missing_module": "Missing module",
        "semantic": "Semantic",
        "fatal": "Fatal",
    }

    for d in diagnostics:
        if d.line is None:
            loc = "—"
        elif d.line_end is not None and d.line_end != d.line:
            loc = f"line {d.line}:{d.col} → line {d.line_end}:{d.col_end}"
        else:
            loc = f"line {d.line}, col {d.col}"

        msg = d.message
        if d.token:
            msg = f'{msg} (token "{d.token}")'

        table.add_row(d.module or "—", loc, _KIND_LABELS.get(d.kind, d.kind), msg)
    return table
