"""Unit tests for the SANY parser wrapper.

Tests cover:
- Parsing of successful SANY output (modules + semantic analysis)
- Parsing of failed output (parse exception, error accumulation)
- SANYRun population via populate_run()
- SANYDiagnostic fields
"""

from datetime import datetime

from tla_cli.wrappers.sany import SANYDiagnostic, SANYOutputParser, SANYRun

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_parser(lines: list[str]) -> SANYOutputParser:
    p = SANYOutputParser()
    for line in lines:
        p.feed_line(line)
    return p


def _make_run() -> SANYRun:
    return SANYRun(started_at=datetime.now())


# ---------------------------------------------------------------------------
# Parsing file lines
# ---------------------------------------------------------------------------


def test_parsing_file_single():
    p = _run_parser(["Parsing file /path/to/Spec.tla"])
    assert p.get_modules_parsed() == ["/path/to/Spec.tla"]


def test_parsing_file_multiple():
    p = _run_parser(
        [
            "Parsing file /path/to/Spec.tla",
            "Parsing file /path/to/Other.tla (jar:file:/foo.jar!/Other.tla)",
        ]
    )
    assert len(p.get_modules_parsed()) == 2


def test_parsing_file_not_matched_for_non_tla():
    p = _run_parser(["Parsing file /path/to/something.cfg"])
    assert p.get_modules_parsed() == []


# ---------------------------------------------------------------------------
# Semantic processing lines
# ---------------------------------------------------------------------------


def test_semantic_processing_single():
    p = _run_parser(["Semantic processing of module Spec"])
    assert p.get_modules_semantic() == ["Spec"]


def test_semantic_processing_multiple():
    lines = [
        "Parsing file /path/to/Naturals.tla",
        "Parsing file /path/to/Spec.tla",
        "Semantic processing of module Naturals",
        "Semantic processing of module Spec",
    ]
    p = _run_parser(lines)
    assert p.get_modules_semantic() == ["Naturals", "Spec"]


def test_semantic_not_confused_with_parse():
    p = _run_parser(["Semantic processing of module Foo"])
    assert p.get_modules_parsed() == []


# ---------------------------------------------------------------------------
# Error parsing
# ---------------------------------------------------------------------------


def test_no_errors_on_success():
    lines = [
        "****** SANY2 Version 2.2 created 08 July 2020",
        "",
        "Parsing file /path/to/Spec.tla",
        "Semantic processing of module Spec",
    ]
    p = _run_parser(lines)
    assert p.get_errors() == []


def test_parse_exception_triggers_error_accumulation():
    lines = [
        "Parsing file /path/to/Spec.tla",
        "SANY2 Parse Exception",
        "Was expecting something else",
        "  Got: EOF",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    assert len(errors) == 1
    assert "Was expecting something else" in errors[0].message


def test_fatal_errors_triggers_error_accumulation():
    lines = [
        "Parsing file /path/to/Spec.tla",
        "Fatal errors while parsing TLA+ spec in file /path/to/Spec.tla",
        "  In module Spec",
        "  Could not parse module Spec",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    assert len(errors) == 1
    assert "In module Spec" in errors[0].message


def test_error_block_not_started_for_errors_line():
    """The '*** Errors: N' line should flush but not start a new block."""
    lines = [
        "SANY2 Parse Exception",
        "Something bad happened",
        "*** Errors: 1",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    # One error block for the parse exception content
    assert len(errors) == 1


def test_multiple_error_blocks():
    lines = [
        "SANY2 Parse Exception",
        "First error",
        "SANY2 Parse Exception",
        "Second error",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    assert len(errors) == 2


def test_empty_lines_not_in_error():
    lines = [
        "SANY2 Parse Exception",
        "Real error line",
        "",
        "",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    assert len(errors) == 1
    assert "Real error line" in errors[0].message


# ---------------------------------------------------------------------------
# populate_run
# ---------------------------------------------------------------------------


def test_populate_run_success():
    lines = [
        "Parsing file /a.tla",
        "Parsing file /b.tla",
        "Semantic processing of module A",
        "Semantic processing of module B",
    ]
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)

    assert run.modules_parsed == ["/a.tla", "/b.tla"]
    assert run.modules_semantic == ["A", "B"]
    assert run.errors == []


def test_populate_run_with_errors():
    lines = [
        "SANY2 Parse Exception",
        "Something went wrong",
    ]
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)

    assert len(run.errors) == 1
    assert run.errors[0].severity == "error"
    assert "Something went wrong" in run.errors[0].message


# ---------------------------------------------------------------------------
# SANYDiagnostic dataclass
# ---------------------------------------------------------------------------


def test_sany_diagnostic_fields():
    d = SANYDiagnostic(severity="error", message="Bad module", module="Foo")
    assert d.severity == "error"
    assert d.message == "Bad module"
    assert d.module == "Foo"


def test_sany_diagnostic_optional_module():
    d = SANYDiagnostic(severity="warning", message="Minor issue")
    assert d.module is None
