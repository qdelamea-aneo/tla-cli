"""Unit tests for the .tlacache caching behavior of tool wrappers.

Contracts under test:
- TLC and SANY: cache_dir is wiped and recreated on every run; log files
  are written there; when cache_dir is None no files are written.
- TLAPM: cache_dir is created (never wiped) so fingerprints accumulate;
  TLAPM_CACHE_DIR env var is set; --nofp / --cleanfp flags are forwarded.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tla_cli.wrappers.sany import SANY
from tla_cli.wrappers.tlaps import TLAPM
from tla_cli.wrappers.tlc import TLC

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_popen(returncode: int = 0, lines: list[str] | None = None):
    proc = MagicMock()
    proc.stdout = iter(lines or [])
    proc.returncode = returncode
    proc.wait.return_value = None
    return proc


def make_tlc() -> TLC:
    return TLC(
        main_class="tlc2.TLC",
        tla2tools_jar=Path("/fake/tla2tools.jar"),
        community_modules_jar=Path("/fake/community.jar"),
        stdlib_dir=Path("/fake/stdlib"),
        logger=MagicMock(),
        console=MagicMock(),
    )


def make_sany() -> SANY:
    return SANY(
        tla2tools_jar=Path("/fake/tla2tools.jar"),
        community_modules_jar=Path("/fake/community.jar"),
        stdlib_dir=Path("/fake/stdlib"),
        logger=MagicMock(),
        console=MagicMock(),
    )


def make_tlapm() -> TLAPM:
    return TLAPM(
        binary_path=Path("/fake/tlapm"),
        community_modules_dir=Path("/fake/community"),
        logger=MagicMock(),
        console=MagicMock(),
    )


# ---------------------------------------------------------------------------
# TLC — cache_dir
# ---------------------------------------------------------------------------


def test_tlc_start_creates_cache_dir(tmp_path):
    cache_dir = tmp_path / "tlc" / "default"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
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

    assert cache_dir.is_dir()


def test_tlc_start_writes_log_and_json(tmp_path):
    cache_dir = tmp_path / "tlc" / "default"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen(lines=["output line\n"])):
        run = make_tlc().start(
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

    assert run.log_file == cache_dir / "tlc.log"
    assert run.log_file.exists()
    assert (cache_dir / "run-data.json").exists()


def test_tlc_start_wipes_existing_cache_dir(tmp_path):
    cache_dir = tmp_path / "tlc" / "default"
    cache_dir.mkdir(parents=True)
    stale = cache_dir / "stale.log"
    stale.write_text("old run data")

    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
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

    assert not stale.exists(), "stale file from previous run should be gone"


def test_tlc_start_no_cache_dir_no_log(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        run = make_tlc().start(
            spec,
            cfg,
            workers=1,
            max_heap_size="1G",
            community_modules=False,
            external_modules=[],
            interactive=False,
            silent=True,
        )

    assert run.log_file is None


# ---------------------------------------------------------------------------
# SANY — cache_dir
# ---------------------------------------------------------------------------


def test_sany_parse_creates_cache_dir(tmp_path):
    cache_dir = tmp_path / "sany"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        make_sany().parse(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert cache_dir.is_dir()


def test_sany_parse_writes_log(tmp_path):
    cache_dir = tmp_path / "sany"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen(lines=["SANY output\n"])):
        run = make_sany().parse(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert run.log_file == cache_dir / "sany.log"
    assert run.log_file.exists()
    assert "SANY output" in run.log_file.read_text()


def test_sany_parse_wipes_existing_cache_dir(tmp_path):
    cache_dir = tmp_path / "sany"
    cache_dir.mkdir()
    stale = cache_dir / "old.log"
    stale.write_text("previous run")

    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        make_sany().parse(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert not stale.exists(), "stale file from previous run should be gone"


def test_sany_parse_no_cache_dir_no_log(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        run = make_sany().parse(spec, interactive=False, silent=True)

    assert run.log_file is None


# ---------------------------------------------------------------------------
# TLAPM — cache_dir (accumulating, never wiped)
# ---------------------------------------------------------------------------


def test_tlapm_prove_creates_cache_dir(tmp_path):
    cache_dir = tmp_path / "tlapm"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        make_tlapm().prove(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert cache_dir.is_dir()


def test_tlapm_prove_preserves_existing_cache_dir_contents(tmp_path):
    """tlapm cache is not wiped between runs so fingerprints accumulate."""
    cache_dir = tmp_path / "tlapm"
    cache_dir.mkdir()
    fingerprint = cache_dir / "fingerprints"
    fingerprint.write_text("fingerprint data")

    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        make_tlapm().prove(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert fingerprint.exists(), "fingerprint file must survive between runs"
    assert fingerprint.read_text() == "fingerprint data"


def test_tlapm_prove_writes_log(tmp_path):
    cache_dir = tmp_path / "tlapm"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen(lines=["tlapm output\n"])):
        run = make_tlapm().prove(spec, interactive=False, silent=True, cache_dir=cache_dir)

    assert run.log_file == cache_dir / "tlapm.log"
    assert run.log_file.exists()


def test_tlapm_prove_no_cache_dir_no_log(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()):
        run = make_tlapm().prove(spec, interactive=False, silent=True)

    assert run.log_file is None


# ---------------------------------------------------------------------------
# TLAPM — TLAPM_CACHE_DIR env var
# ---------------------------------------------------------------------------


def test_tlapm_prove_sets_cache_dir_env(tmp_path):
    cache_dir = tmp_path / "tlapm"
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlapm().prove(spec, interactive=False, silent=True, cache_dir=cache_dir)

    env = mock_popen.call_args[1]["env"]
    assert env is not None
    assert env["TLAPM_CACHE_DIR"] == str(cache_dir)


def test_tlapm_prove_no_cache_dir_no_env(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlapm().prove(spec, interactive=False, silent=True)

    assert mock_popen.call_args[1]["env"] is None


# ---------------------------------------------------------------------------
# TLAPM — --nofp / --cleanfp flags
# ---------------------------------------------------------------------------


def test_tlapm_prove_nofp_flag_forwarded(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlapm().prove(spec, interactive=False, silent=True, nofp=True)

    cmd = mock_popen.call_args[0][0]
    assert "--nofp" in cmd


def test_tlapm_prove_cleanfp_flag_forwarded(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlapm().prove(spec, interactive=False, silent=True, cleanfp=True)

    cmd = mock_popen.call_args[0][0]
    assert "--cleanfp" in cmd


def test_tlapm_prove_no_fp_flags_by_default(tmp_path):
    spec = tmp_path / "Spec.tla"
    spec.write_text("")

    with patch("subprocess.Popen", return_value=_mock_popen()) as mock_popen:
        make_tlapm().prove(spec, interactive=False, silent=True)

    cmd = mock_popen.call_args[0][0]
    assert "--nofp" not in cmd
    assert "--cleanfp" not in cmd
