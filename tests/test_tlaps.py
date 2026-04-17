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

import pytest

from datetime import datetime
from tla_cli.tools.tlaps import (
    TLAPMObligation,
    TLAPMOutputParser,
    TLAPMRun,
    TO_BE_PROVED,
    BEING_PROVED,
    PROVED,
    TRIVIAL,
    FAILED,
    OMITTED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_parser(lines: list[str]) -> TLAPMOutputParser:
    p = TLAPMOutputParser()
    for line in lines:
        p.feed_line(line)
    return p


def _obl_block(obl_id: int, status: str, prover: str = "", reason: str = "",
               loc: str = "10:1:10:10", already: str = "") -> list[str]:
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
    lines = (
        _obl_block(1, TO_BE_PROVED)
        + _obl_block(1, PROVED, prover="smt")
    )
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
    lines = (
        _obl_block(1, PROVED, prover="zenon")
        + _obl_block(2, TRIVIAL, prover="tlapm")
    )
    p = _run_parser(lines)
    run = _make_run()
    p.populate_run(run)

    assert len(run.obligations) == 2
    assert run.obligations[1].prover == "zenon"
    assert run.obligations[2].status == TRIVIAL


def test_populate_run_uses_info_line():
    lines = (
        _obl_block(1, PROVED)
        + ["[INFO]: All 10 obligations proved."]
    )
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
