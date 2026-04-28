"""Unit tests for the TLAPS prover output parser.

Tests cover:
- Parsing @!!BEGIN/@!!END blocks
- Obligation tracking (creation, status updates)
- Warning and error block parsing
- Multi-line field values (@!!obl: continuation)
- Final INFO line parsing for total obligation count
- TLAPMRun property calculations (num_proved, num_failed, num_pending)
- populate_run() field transfer
"""

from datetime import datetime

from tla_cli.wrappers.tlaps import (
    BEING_PROVED,
    FAILED,
    INTERRUPTED,
    OMITTED,
    PROVED,
    TO_BE_PROVED,
    TRIVIAL,
    UNKNOWN,
    TLAPMObligation,
    TLAPMOutputParser,
    TLAPMRun,
    _parse_loc,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_parser(lines: list[str]) -> TLAPMOutputParser:
    p = TLAPMOutputParser()
    for line in lines:
        p.feed_line(line)
    return p


def _obl_block(obl_id: int, status: str, prover: str = "", reason: str = "", loc: str = "10:1:10:10", already: str = "") -> list[str]:
    lines = [
        "@!!BEGIN",
        "@!!type:obligation",
        f"@!!id:{obl_id}",
        f"@!!loc:{loc}",
        f"@!!status:{status}",
    ]
    if prover:
        lines.append(f"@!!prover:{prover}")
    if reason:
        lines.append(f"@!!reason:{reason}")
    if already:
        lines.append(f"@!!already:{already}")
    lines.append("@!!END")
    return lines


def _warning_block(msg: str) -> list[str]:
    return ["@!!BEGIN", "@!!type:warning", f"@!!msg:{msg}", "@!!END"]


def _error_block(msg: str) -> list[str]:
    return ["@!!BEGIN", "@!!type:error", f"@!!msg:{msg}", "@!!END"]


def _make_run() -> TLAPMRun:
    return TLAPMRun(started_at=datetime.now())


# ---------------------------------------------------------------------------
# Basic block parsing
# ---------------------------------------------------------------------------


def test_single_obligation_to_be_proved():
    lines = _obl_block(1, TO_BE_PROVED)
    p = _run_parser(lines)
    obls = p.get_obligations()
    assert 1 in obls
    assert obls[1].id == 1
    assert obls[1].status == TO_BE_PROVED


def test_obligation_with_location():
    lines = _obl_block(5, PROVED, loc="42:3:42:25")
    p = _run_parser(lines)
    assert p.get_obligations()[5].loc == "42:3:42:25"


def test_obligation_with_prover():
    lines = _obl_block(1, PROVED, prover="zenon")
    p = _run_parser(lines)
    assert p.get_obligations()[1].prover == "zenon"


def test_obligation_with_reason():
    lines = _obl_block(3, FAILED, reason="timeout")
    p = _run_parser(lines)
    assert p.get_obligations()[3].reason == "timeout"


def test_obligation_already_true():
    lines = _obl_block(1, PROVED, already="true")
    p = _run_parser(lines)
    assert p.get_obligations()[1].already is True


def test_obligation_already_false():
    lines = _obl_block(1, PROVED, already="false")
    p = _run_parser(lines)
    assert p.get_obligations()[1].already is False


# ---------------------------------------------------------------------------
# Obligation status updates
# ---------------------------------------------------------------------------


def test_obligation_status_updated():
    """First block has 'to be proved', second block updates to 'proved'."""
    lines = _obl_block(1, TO_BE_PROVED) + _obl_block(1, PROVED, prover="smt")
    p = _run_parser(lines)
    obls = p.get_obligations()
    assert len(obls) == 1
    assert obls[1].status == PROVED
    assert obls[1].prover == "smt"


def test_multiple_obligations():
    lines = (
        _obl_block(1, TO_BE_PROVED)
        + _obl_block(2, TO_BE_PROVED)
        + _obl_block(3, TO_BE_PROVED)
        + _obl_block(1, PROVED)
        + _obl_block(2, TRIVIAL)
        + _obl_block(3, FAILED)
    )
    p = _run_parser(lines)
    obls = p.get_obligations()
    assert len(obls) == 3
    assert obls[1].status == PROVED
    assert obls[2].status == TRIVIAL
    assert obls[3].status == FAILED


# ---------------------------------------------------------------------------
# Warning and error blocks
# ---------------------------------------------------------------------------


def test_warning_parsed():
    lines = _warning_block("Some warning message")
    p = _run_parser(lines)
    assert p.get_warnings() == ["Some warning message"]


def test_error_parsed():
    lines = _error_block("Something failed badly")
    p = _run_parser(lines)
    assert p.get_errors() == ["Something failed badly"]


def test_multiple_warnings():
    lines = _warning_block("warn 1") + _warning_block("warn 2")
    p = _run_parser(lines)
    assert len(p.get_warnings()) == 2


def test_empty_warning_ignored():
    lines = ["@!!BEGIN", "@!!type:warning", "@!!msg:", "@!!END"]
    p = _run_parser(lines)
    assert p.get_warnings() == []


# ---------------------------------------------------------------------------
# Multi-line field values
# ---------------------------------------------------------------------------


def test_multiline_obl_field():
    lines = [
        "@!!BEGIN",
        "@!!type:obligation",
        "@!!id:1",
        "@!!loc:10:1:10:10",
        "@!!status:to be proved",
        "@!!obl:ASSUME NEW CONSTANT Agent,",
        "       NEW CONSTANT Task",
        "PROVE  Something",
        "@!!END",
    ]
    p = _run_parser(lines)
    obls = p.get_obligations()
    assert 1 in obls
    assert "ASSUME NEW CONSTANT Agent," in (obls[1].obl or "")
    assert "PROVE  Something" in (obls[1].obl or "")


def test_obl_field_captured_on_update():
    """obl field must be captured when an obligation is updated."""
    initial = _obl_block(1, TO_BE_PROVED)
    update = [
        "@!!BEGIN",
        "@!!type:obligation",
        "@!!id:1",
        "@!!loc:10:1:10:10",
        "@!!status:failed",
        "@!!prover:zenon",
        "@!!obl:PROVE FALSE",
        "@!!END",
    ]
    p = _run_parser(initial + update)
    assert p.get_obligations()[1].obl == "PROVE FALSE"


def test_obl_field_absent_when_not_emitted():
    lines = _obl_block(1, PROVED)
    p = _run_parser(lines)
    assert p.get_obligations()[1].obl is None


def test_multiline_msg_in_warning():
    lines = [
        "@!!BEGIN",
        "@!!type:warning",
        "@!!msg:Line 1",
        "Line 2",
        "Line 3",
        "@!!END",
    ]
    p = _run_parser(lines)
    warnings = p.get_warnings()
    assert len(warnings) == 1
    assert "Line 1" in warnings[0]
    assert "Line 2" in warnings[0]
    assert "Line 3" in warnings[0]


# ---------------------------------------------------------------------------
# INFO line parsing
# ---------------------------------------------------------------------------


def test_info_all_obligations_proved():
    lines = [
        "[INFO]: All 42 obligations proved.",
    ]
    p = _run_parser(lines)
    assert p.get_num_obligations() == 42


def test_info_line_variants():
    p = _run_parser(["[INFO] All 10 obligations proved."])
    assert p.get_num_obligations() == 10


def test_num_obligations_from_ids_when_no_info_line():
    lines = _obl_block(1, PROVED) + _obl_block(2, PROVED) + _obl_block(3, TRIVIAL)
    p = _run_parser(lines)
    # No INFO line, should fall back to number of distinct obligation IDs
    assert p.get_num_obligations() == 3


# ---------------------------------------------------------------------------
# TLAPMRun properties
# ---------------------------------------------------------------------------


def test_run_num_proved():
    run = TLAPMRun(
        started_at=datetime.now(),
        obligations={
            1: TLAPMObligation(id=1, loc="", status=PROVED),
            2: TLAPMObligation(id=2, loc="", status=TRIVIAL),
            3: TLAPMObligation(id=3, loc="", status=FAILED),
        },
    )
    assert run.num_proved == 2


def test_run_num_failed():
    run = TLAPMRun(
        started_at=datetime.now(),
        obligations={
            1: TLAPMObligation(id=1, loc="", status=PROVED),
            2: TLAPMObligation(id=2, loc="", status=FAILED),
            3: TLAPMObligation(id=3, loc="", status=FAILED),
        },
    )
    assert run.num_failed == 2


def test_run_num_pending():
    run = TLAPMRun(
        started_at=datetime.now(),
        obligations={
            1: TLAPMObligation(id=1, loc="", status=TO_BE_PROVED),
            2: TLAPMObligation(id=2, loc="", status=BEING_PROVED),
            3: TLAPMObligation(id=3, loc="", status=PROVED),
        },
    )
    assert run.num_pending == 2


def test_run_num_proved_empty():
    run = TLAPMRun(started_at=datetime.now())
    assert run.num_proved == 0
    assert run.num_failed == 0
    assert run.num_pending == 0


# ---------------------------------------------------------------------------
# populate_run
# ---------------------------------------------------------------------------


def test_populate_run_transfers_obligations():
    lines = _obl_block(1, PROVED, prover="zenon") + _obl_block(2, TRIVIAL, prover="tlapm")
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)

    assert len(run.obligations) == 2
    assert run.obligations[1].prover == "zenon"
    assert run.obligations[2].status == TRIVIAL


def test_populate_run_uses_info_line():
    lines = _obl_block(1, PROVED) + ["[INFO]: All 10 obligations proved."]
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)
    assert run.num_obligations == 10


def test_populate_run_errors_and_warnings():
    lines = _warning_block("a warning") + _error_block("an error")
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)
    assert "a warning" in run.warnings
    assert "an error" in run.errors


# ---------------------------------------------------------------------------
# Lines outside blocks are ignored gracefully
# ---------------------------------------------------------------------------


def test_non_block_lines_ignored():
    lines = [
        r"\* TLAPM version c706ff1",
        r"\* launched at 2026-01-01",
        "",
        "(* loading fingerprints ... *)",
        "(* fingerprints written ... *)",
    ] + _obl_block(1, PROVED)
    p = _run_parser(lines)
    assert len(p.get_obligations()) == 1


def test_incomplete_block_handled_gracefully():
    """A block without @!!END should not crash."""
    lines = [
        "@!!BEGIN",
        "@!!type:obligation",
        "@!!id:1",
        # No @!!END
    ]
    p = _run_parser(lines)
    # No crash; obligation not committed since block was never closed
    assert len(p.get_obligations()) == 0


# ---------------------------------------------------------------------------
# _parse_loc
# ---------------------------------------------------------------------------


def test_parse_loc_valid():
    assert _parse_loc("10:1:10:25") == (10, 1, 10, 25)


def test_parse_loc_valid_multidigit():
    assert _parse_loc("100:3:102:40") == (100, 3, 102, 40)


def test_parse_loc_empty_string():
    assert _parse_loc("") is None


def test_parse_loc_too_few_parts():
    assert _parse_loc("10:1") is None


def test_parse_loc_non_numeric():
    assert _parse_loc("a:b:c:d") is None


def test_parse_loc_too_many_parts():
    assert _parse_loc("10:1:10:25:99") is None


# ---------------------------------------------------------------------------
# Issue 11 — tlapm crash shows confusing "0/0 obligation(s) failed"
# ---------------------------------------------------------------------------


def test_show_summary_crash_no_obligations():
    """When tlapm_run.success=False and num_obligations=0, the output must NOT
    contain '0/0 obligation(s)' and must contain a crash-specific message."""
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = False
    run.num_obligations = 0
    run.errors = ["Cannot parse module TestModule"]

    display.show_summary(run)
    output = buf.getvalue()

    assert "0/0 obligation(s)" not in output
    # Should mention the error or a fallback message
    assert ("tlapm error" in output) or ("no obligations were checked" in output)


def test_show_summary_crash_no_obligations_no_errors():
    """When tlapm crashed with no obligations and no error messages, show fallback."""
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = False
    run.num_obligations = 0

    display.show_summary(run)
    output = buf.getvalue()

    assert "0/0 obligation(s)" not in output
    assert "no obligations were checked" in output


# ---------------------------------------------------------------------------
# Issue 12 — Rich [/dim] markup leaks when obligation text is truncated
# ---------------------------------------------------------------------------


def test_obligation_text_escaped():
    """Obligation text containing Rich markup characters must not produce raw
    markup tags in the output — they should be escaped."""
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay, FAILED

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = False
    run.num_obligations = 1
    # obl text with Rich markup chars that should be escaped
    run.obligations = {
        1: TLAPMObligation(id=1, loc="10:1:10:20", status=FAILED,
                           obl=r"ASSUME NEW x \in [1..10] PROVE x > 0")
    }

    # Should not raise; the [1..10] brackets must be escaped
    display.show_summary(run)
    output = buf.getvalue()
    assert "obligation(s) failed" in output


def test_obligation_text_shown_in_full():
    """Long obligation text must be shown in full (no truncation), with each line
    rendered separately so the panel can wrap them naturally."""
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay, FAILED

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True, width=200)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = False
    run.num_obligations = 1
    multi_line_obl = "ASSUME NEW x \\in 1..10\nPROVE " + ("y" * 250)
    run.obligations = {
        1: TLAPMObligation(id=1, loc="10:1:10:20", status=FAILED, obl=multi_line_obl)
    }

    display.show_summary(run)
    output = buf.getvalue()
    assert "obligation(s) failed" in output
    assert "ASSUME NEW x" in output
    # All 250 y's are preserved — Rich may visually wrap a long line across
    # multiple panel rows, but the total character count must be intact.
    assert output.count("y") == 250
    # No mid-content truncation marker (the previous 200-char limit added "…").
    assert "…" not in output


# ---------------------------------------------------------------------------
# Omitted / interrupted / unproved counts
# ---------------------------------------------------------------------------


def test_run_num_omitted_and_interrupted():
    run = TLAPMRun(
        started_at=datetime.now(),
        obligations={
            1: TLAPMObligation(id=1, loc="", status=PROVED),
            2: TLAPMObligation(id=2, loc="", status=OMITTED),
            3: TLAPMObligation(id=3, loc="", status=OMITTED),
            4: TLAPMObligation(id=4, loc="", status=INTERRUPTED),
        },
    )
    assert run.num_omitted == 2
    assert run.num_interrupted == 1


def test_run_num_unproved_counts_unknown_and_pending():
    run = TLAPMRun(
        started_at=datetime.now(),
        obligations={
            1: TLAPMObligation(id=1, loc="", status=PROVED),
            2: TLAPMObligation(id=2, loc="", status=UNKNOWN),
            3: TLAPMObligation(id=3, loc="", status=BEING_PROVED),
        },
    )
    assert run.num_unproved == 2


def test_run_num_unproved_includes_missing_obligations():
    """When the INFO line reports more obligations than tlapm emitted blocks for
    (e.g. the run was killed before they were reported), the missing ones count
    as unproved."""
    run = TLAPMRun(
        started_at=datetime.now(),
        num_obligations=5,
        obligations={
            1: TLAPMObligation(id=1, loc="", status=PROVED),
            2: TLAPMObligation(id=2, loc="", status=PROVED),
        },
    )
    assert run.num_unproved == 3


def test_summary_reports_omitted_on_success():
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True, width=120)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = True
    run.num_obligations = 3
    run.obligations = {
        1: TLAPMObligation(id=1, loc="", status=PROVED),
        2: TLAPMObligation(id=2, loc="", status=PROVED),
        3: TLAPMObligation(id=3, loc="", status=OMITTED),
    }

    display.show_summary(run)
    output = buf.getvalue()
    assert "1 omitted" in output


def test_summary_reports_unproved_on_failure():
    from io import StringIO
    from rich.console import Console
    from tla_cli.wrappers.tlaps import TLAPMOutputDisplay

    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=True, width=120)
    display = TLAPMOutputDisplay(console, "TestModule", interactive=False, silent=False)

    run = TLAPMRun(started_at=datetime.now())
    run.success = False
    run.num_obligations = 4
    run.obligations = {
        1: TLAPMObligation(id=1, loc="10:1:10:5", status=FAILED, reason="timeout"),
        2: TLAPMObligation(id=2, loc="", status=OMITTED),
        3: TLAPMObligation(id=3, loc="", status=INTERRUPTED),
        4: TLAPMObligation(id=4, loc="", status=UNKNOWN),
    }

    display.show_summary(run)
    output = buf.getvalue()
    assert "1/4 obligation(s) failed" in output
    assert "1 omitted" in output
    assert "1 interrupted" in output
    assert "1 unproved" in output
