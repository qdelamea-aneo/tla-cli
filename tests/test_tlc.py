"""Unit tests for the TLC tool interface (TLC and TLCRun).

These tests focus on :meth:`~cli.tools.tlc.TLC._parse_failure`, which maps
TLC exit codes to ``error_kind`` values, and the interaction between the
output parser and the failure handler.

No real TLC process is launched — all subprocess calls are mocked.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tla_cli.wrappers.tlc import TLC, TLCRun

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tlc() -> TLC:
    """Create a :class:`TLC` instance with all dependencies mocked."""
    return TLC(
        main_class="tlc2.TLC",
        tla2tools_jar=Path("/fake/tla2tools.jar"),
        community_modules_jar=Path("/fake/community.jar"),
        stdlib_dir=Path("/fake/stdlib"),
        logger=MagicMock(),
        console=MagicMock(),
    )


def fresh_run() -> TLCRun:
    """Return a new :class:`TLCRun` ready for testing."""
    return TLCRun(started_at=datetime.now())


# ---------------------------------------------------------------------------
# Tests — exit-code-to-error-kind mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exit_code", "expected_kind", "expected_type"),
    [
        (10, "assumption_violation", "Assumption failure"),
        (11, "deadlock", "Deadlock failure"),
        (12, "safety_violation", "Safety failure"),
        (13, "liveness_violation", "Liveness failure"),
        (1, "runtime_error", "Error"),
        (99, "unknown", "Unknown error (exit 99)"),
    ],
)
def test_parse_failure_exit_code_mapping(exit_code, expected_kind, expected_type):
    tlc = make_tlc()
    run = fresh_run()
    tlc._parse_failure(run, "", exit_code)
    assert run.success is False
    assert run.error_kind == expected_kind
    assert run.error_type == expected_type


def test_parse_failure_sets_success_false():
    tlc = make_tlc()
    run = fresh_run()
    tlc._parse_failure(run, "", 11)
    assert run.success is False


# ---------------------------------------------------------------------------
# Tests — parser-set error_kind is preserved
# ---------------------------------------------------------------------------


def test_parse_failure_preserves_config_not_found():
    """If the parser already classified the error as config_not_found,
    _parse_failure must not overwrite it with the exit-code kind."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_kind = "config_not_found"  # set by parser
    tlc._parse_failure(run, "", 255)
    assert run.error_kind == "config_not_found"


def test_parse_failure_preserves_semantic_error():
    """Parser-set semantic_error must survive _parse_failure."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_kind = "semantic_error"  # set by parser
    tlc._parse_failure(run, "", 1)
    assert run.error_kind == "semantic_error"


# ---------------------------------------------------------------------------
# Tests — raw error_msg fallback
# ---------------------------------------------------------------------------


def test_parse_failure_raw_fallback_when_no_msg():
    """When error_msg is None and output contains Error:, extract from output."""
    tlc = make_tlc()
    run = fresh_run()
    tlc._parse_failure(run, "Some preamble\nError: Something broke\nExtra", 1)
    assert run.error_msg is not None
    assert "Something broke" in run.error_msg


def test_parse_failure_no_fallback_for_config_error():
    """Raw fallback must be skipped for config_not_found even if output has Error:."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_kind = "config_not_found"
    run.error_msg = "/path/to/Foo.cfg"  # already set by parser
    tlc._parse_failure(run, "Error: Failed to open the configuration file", 255)
    assert run.error_msg == "/path/to/Foo.cfg"  # unchanged


def test_parse_failure_no_fallback_for_semantic_error():
    """Raw fallback must be skipped for semantic_error (diagnostics table is used)."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_kind = "semantic_error"
    # error_msg is None for semantic errors (set by populate_run)
    tlc._parse_failure(run, "Error: Parsing or semantic analysis failed.", 150)
    assert run.error_msg is None


def test_parse_failure_no_fallback_when_msg_already_set():
    """If the parser already set error_msg, the fallback must not overwrite it."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_msg = "precise message from parser"
    run.error_kind = "runtime_error"
    tlc._parse_failure(run, "Error: Something else", 1)
    assert run.error_msg == "precise message from parser"


# ---------------------------------------------------------------------------
# Tests — error_type labels
# ---------------------------------------------------------------------------


def test_error_type_for_known_exit_codes():
    tlc = make_tlc()
    expected = {
        0: "Success",
        1: "Error",
        10: "Assumption failure",
        11: "Deadlock failure",
        12: "Safety failure",
        13: "Liveness failure",
    }
    for code, label in expected.items():
        assert tlc.tlc_exit_codes[code] == label


def test_error_type_unknown_with_msg():
    """Exit code not in map but parser set error_msg → error_type = 'Error'."""
    tlc = make_tlc()
    run = fresh_run()
    run.error_msg = "something"
    tlc._parse_failure(run, "", 42)
    assert run.error_type == "Error"
    assert run.error_kind == "unknown"


def test_error_type_unknown_without_msg():
    """Exit code not in map and no error_msg → include raw exit code."""
    tlc = make_tlc()
    run = fresh_run()
    tlc._parse_failure(run, "", 42)
    assert "42" in (run.error_type or "")


# ---------------------------------------------------------------------------
# Tests — TLCRun dataclass defaults
# ---------------------------------------------------------------------------


def test_tlcrun_defaults():
    run = TLCRun(started_at=datetime.now())
    assert run.success is None
    assert run.trace is None
    assert run.diagnostics is None
    assert run.error_kind is None
    assert run.error_msg is None
    assert run.coverage is None
    assert run.progress_history is None


# ---------------------------------------------------------------------------
# Helpers for subprocess-level tests
# ---------------------------------------------------------------------------


def _mock_popen(returncode: int = 0, lines: list[str] | None = None):
    proc = MagicMock()
    proc.stdout = iter(lines or [])
    proc.returncode = returncode
    proc.wait.return_value = None
    return proc


# ---------------------------------------------------------------------------
# Issue 05 — --export-json uses -dumpTrace json, not -dump json
# ---------------------------------------------------------------------------


def test_export_json_uses_dumptrace(tmp_path):
    """When export_json=True the command must include -dumpTrace, not -dump json."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().start(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            export_json=True,
            interactive=False,
            silent=True,
            cache_dir=tmp_path / "cache",
        )

    cmd = mock_popen.call_args[0][0]
    assert "-dumpTrace" in cmd
    assert "-dump" not in cmd or cmd[cmd.index("-dump") + 1] not in ("json",)


def test_export_json_sets_states_file(tmp_path):
    """When export_json=True, run.states_file must point to a path ending trace.json."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")
    cache_dir = tmp_path / "cache"

    with patch("subprocess.Popen", return_value=_mock_popen()):
        run = make_tlc().start(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            export_json=True,
            interactive=False,
            silent=True,
            cache_dir=cache_dir,
        )

    assert run.states_file is not None
    assert run.states_file.name == "trace.json"


def test_export_json_false_no_dumptrace(tmp_path):
    """When export_json=False, -dumpTrace must not appear in the command."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().start(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            export_json=False,
            interactive=False,
            silent=True,
            cache_dir=tmp_path / "cache",
        )

    cmd = mock_popen.call_args[0][0]
    assert "-dumpTrace" not in cmd


# ---------------------------------------------------------------------------
# Issue 06 — --num-traces uses -simulate num=N, not -numTraces
# ---------------------------------------------------------------------------


def test_num_traces_uses_simulate_num(tmp_path):
    """When num_traces=10, the command must contain '-simulate' and 'num=10',
    and must NOT contain '-numTraces'."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().simulate(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            num_traces=10,
            interactive=False,
            silent=True,
            cache_dir=tmp_path / "cache",
        )

    cmd = mock_popen.call_args[0][0]
    assert "-simulate" in cmd
    assert "num=10" in cmd
    assert "-numTraces" not in cmd


def test_num_traces_none_uses_plain_simulate(tmp_path):
    """When num_traces=None, '-simulate' appears without any 'num=' argument."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().simulate(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            num_traces=None,
            interactive=False,
            silent=True,
            cache_dir=tmp_path / "cache",
        )

    cmd = mock_popen.call_args[0][0]
    assert "-simulate" in cmd
    assert not any(arg.startswith("num=") for arg in cmd)


def test_num_traces_correctly_ordered(tmp_path):
    """-simulate [num=N] must appear before -workers in the command."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().simulate(
            spec,
            cfg,
            workers=2,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            num_traces=5,
            interactive=False,
            silent=True,
            cache_dir=tmp_path / "cache",
        )

    cmd = mock_popen.call_args[0][0]
    sim_idx = cmd.index("-simulate")
    num_idx = cmd.index("num=5")
    workers_idx = cmd.index("-workers")
    assert sim_idx < num_idx < workers_idx


# ---------------------------------------------------------------------------
# Issue 13 — TTrace files redirected to cache dir via -teSpecOutDir
# ---------------------------------------------------------------------------


def test_tespecdoutdir_passed_to_start(tmp_path):
    """When cache_dir is provided to start(), -teSpecOutDir must appear in args."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")
    cache_dir = tmp_path / "cache"

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().start(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            interactive=False,
            silent=True,
            cache_dir=cache_dir,
        )

    cmd = mock_popen.call_args[0][0]
    assert "-teSpecOutDir" in cmd
    te_idx = cmd.index("-teSpecOutDir")
    assert cmd[te_idx + 1] == str(cache_dir)


def test_tespecdoutdir_passed_to_simulate(tmp_path):
    """When cache_dir is provided to simulate(), -teSpecOutDir must appear in args."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")
    cache_dir = tmp_path / "cache"

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlc().simulate(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            interactive=False,
            silent=True,
            cache_dir=cache_dir,
        )

    cmd = mock_popen.call_args[0][0]
    assert "-teSpecOutDir" in cmd
    te_idx = cmd.index("-teSpecOutDir")
    assert cmd[te_idx + 1] == str(cache_dir)
