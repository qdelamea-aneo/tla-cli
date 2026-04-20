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
    """Inside a parse-exception block, '*** Errors: N' flushes but does not re-enter."""
    lines = [
        "SANY2 Parse Exception",
        "Something bad happened",
        "*** Errors: 1",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    # One error block for the parse exception content
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# has_errors() — error flag from *** Errors: N
# ---------------------------------------------------------------------------


def test_has_errors_false_with_no_errors():
    p = _run_parser(["Parsing file /a.tla", "Semantic processing of module A"])
    assert p.has_errors() is False


def test_has_errors_true_after_errors_line_nonzero():
    """*** Errors: 1 with no preceding exception block → has_errors() is True."""
    p = _run_parser(["*** Errors: 1"])
    assert p.has_errors() is True


def test_has_errors_false_after_errors_line_zero():
    """*** Errors: 0 must not set the error flag."""
    p = _run_parser(["*** Errors: 0"])
    assert p.has_errors() is False


def test_has_errors_true_from_parse_exception():
    """Accumulated parse-exception content also makes has_errors() True."""
    lines = [
        "SANY2 Parse Exception",
        "Oops",
    ]
    p = _run_parser(lines)
    assert p.has_errors() is True


# ---------------------------------------------------------------------------
# Semantic error format: content follows *** Errors: N
# ---------------------------------------------------------------------------


def test_semantic_error_content_captured_after_errors_line():
    """When *** Errors: N appears outside a parse-exception block, the
    location + message lines that follow must be captured as a diagnostic."""
    lines = [
        "Parsing file /Spec.tla",
        "Semantic processing of module Spec",
        "Semantic errors:",
        "",
        "*** Errors: 1",
        "",
        "line 9, col 14 to line 9, col 26 of module Spec",
        "",
        "Unknown operator: `undeclaredVar'.",
    ]
    p = _run_parser(lines)
    errors = p.get_errors()
    assert len(errors) == 1
    assert "Unknown operator" in errors[0].message
    assert "line 9" in errors[0].message


def test_semantic_error_has_errors_flag_set():
    lines = [
        "Semantic errors:",
        "",
        "*** Errors: 1",
        "",
        "line 9, col 14 to line 9, col 26 of module Spec",
        "",
        "Unknown operator: `undeclaredVar'.",
    ]
    p = _run_parser(lines)
    assert p.has_errors() is True


def test_semantic_errors_header_alone_does_not_set_flag():
    """The 'Semantic errors:' header by itself (without *** Errors: N > 0) must not
    set the flag — the header may appear even with zero errors in some SANY versions."""
    lines = [
        "Parsing file /Spec.tla",
        "Semantic processing of module Spec",
        "Semantic errors:",
        "",
        "*** Errors: 0",
    ]
    p = _run_parser(lines)
    assert p.has_errors() is False


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
