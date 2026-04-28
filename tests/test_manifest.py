"""Unit tests for the manifest model classes.

Tests cover:
- YAML loading and parsing of all field types
- Duration (timedelta) coercion from "H:MM:SS" strings
- Dependencies.community_modules coercion (typo tolerance)
- Dependencies.external_modules coercion (single string → list)
- ModelSettings.workers "auto" support
- Proof and Model check field validation
- Path resolution via model_validator
- ActionResult.overall_ok semantics (issue 08)
- load_manifest error handling (issue 15)
- Skipped ActionResult tracking (issue 16)
"""

from datetime import timedelta
from pathlib import Path

import click
import pytest
from pydantic import ValidationError

from tla_cli.manifest import (
    Dependencies,
    Manifest,
    Model,
    ModelChecks,
    ModelSettings,
    Module,
    Proof,
    ProofChecks,
    ProofSettings,
)
from tla_cli.manifest.models import ActionResult, _parse_duration

# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------


def test_parse_duration_hms():
    assert _parse_duration("0:01:00") == timedelta(minutes=1)


def test_parse_duration_hms_with_hours():
    assert _parse_duration("1:30:00") == timedelta(hours=1, minutes=30)


def test_parse_duration_seconds():
    assert _parse_duration("0:00:45") == timedelta(seconds=45)


def test_parse_duration_none():
    assert _parse_duration(None) is None


def test_parse_duration_timedelta_passthrough():
    td = timedelta(minutes=5)
    assert _parse_duration(td) is td


def test_parse_duration_invalid():
    with pytest.raises(ValueError, match="Cannot parse duration"):
        _parse_duration("5 minutes")


def test_model_timeout_parsed():
    m = Model(
        name="x",
        path=Path("/tmp"),
        timeout="0:02:30",
        type="explicit",
        mode="exhaustive",
        checks=ModelChecks(success=True),
    )
    assert m.timeout == timedelta(minutes=2, seconds=30)


def test_proof_timeout_parsed():
    p = Proof(
        name="x",
        path=Path("/tmp"),
        timeout="0:10:00",
        checks=ProofChecks(success=True),
    )
    assert p.timeout == timedelta(minutes=10)


def test_model_timeout_none():
    m = Model(
        name="x",
        path=Path("/tmp"),
        type="explicit",
        mode="exhaustive",
        checks=ModelChecks(success=True),
    )
    assert m.timeout is None


# ---------------------------------------------------------------------------
# ModelSettings
# ---------------------------------------------------------------------------


def test_model_settings_defaults():
    s = ModelSettings()
    assert s.workers == 1
    assert s.max_heap_size == "1G"


def test_model_settings_auto_workers():
    s = ModelSettings(workers="auto")
    assert s.workers == "auto"


def test_model_settings_int_workers():
    s = ModelSettings(workers=4)
    assert s.workers == 4


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def test_dependencies_community_modules_bool():
    d = Dependencies(community_modules=True)
    assert d.community_modules is True


def test_dependencies_community_modules_string_true():
    d = Dependencies(community_modules="true")
    assert d.community_modules is True


def test_dependencies_community_modules_typo():
    """Accept 'tru' as a common typo for 'true'."""
    d = Dependencies(community_modules="tru")
    assert d.community_modules is True


def test_dependencies_community_modules_false():
    d = Dependencies(community_modules=False)
    assert d.community_modules is False


def test_dependencies_community_modules_string_false():
    d = Dependencies(community_modules="false")
    assert d.community_modules is False


def test_dependencies_external_modules_single_string():
    d = Dependencies(external_modules="/path/to/foo.jar")
    assert d.external_modules == [Path("/path/to/foo.jar")]


def test_dependencies_external_modules_list():
    d = Dependencies(external_modules=["/a.jar", "/b.jar"])
    assert len(d.external_modules) == 2


def test_dependencies_external_modules_default_empty():
    d = Dependencies()
    assert d.external_modules == []


def test_dependencies_external_modules_none():
    d = Dependencies(external_modules=None)
    assert d.external_modules == []


# ---------------------------------------------------------------------------
# ModelChecks
# ---------------------------------------------------------------------------


def test_model_checks_success_only():
    c = ModelChecks(success=True)
    assert c.success is True
    assert c.total_states is None
    assert c.distinct_states is None
    assert c.state_depth is None


def test_model_checks_full():
    c = ModelChecks(
        success=True,
        total_states=1234,
        distinct_states=567,
        state_depth=8,
    )
    assert c.total_states == 1234
    assert c.distinct_states == 567
    assert c.state_depth == 8


def test_model_checks_failure_with_error_type():
    c = ModelChecks(success=False, error_type="Deadlock failure")
    assert c.error_type == "Deadlock failure"


# ---------------------------------------------------------------------------
# ProofChecks
# ---------------------------------------------------------------------------


def test_proof_checks_defaults():
    c = ProofChecks(success=True)
    assert c.num_obligations is None


def test_proof_checks_with_obligations():
    c = ProofChecks(success=True, num_obligations=42)
    assert c.num_obligations == 42


# ---------------------------------------------------------------------------
# ProofSettings
# ---------------------------------------------------------------------------


def test_proof_settings_defaults():
    s = ProofSettings()
    assert s.stretch is None


def test_proof_settings_with_stretch():
    s = ProofSettings(stretch=2.0)
    assert s.stretch == 2.0


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------


def test_module_defaults():
    m = Module(path=Path("/tmp/Spec.tla"))
    assert m.models == []
    assert m.proofs == []
    assert m.dependencies.community_modules is False


# ---------------------------------------------------------------------------
# Manifest.load_manifest (integration test)
# ---------------------------------------------------------------------------


def test_load_manifest_yaml(tmp_path):
    """Test that a well-formed YAML manifest loads correctly."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("SPECIFICATION Spec\n")
    proof = tmp_path / "Spec_proofs.tla"
    proof.write_text("---- MODULE Spec_proofs ----\n====\n")

    manifest_text = f"""
modules:
  - path: {spec.name}
    models:
      - name: small
        path: {cfg.name}
        timeout: "0:01:00"
        type: explicit
        mode: exhaustive
        checks:
          success: true
          total_states: 100
    proofs:
      - name: all
        path: {proof.name}
        timeout: "0:05:00"
        settings:
          stretch: 2
        checks:
          success: true
          num_obligations: 10
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)

    assert len(m.modules) == 1
    mod = m.modules[0]
    assert mod.path == spec
    assert len(mod.models) == 1
    assert mod.models[0].name == "small"
    assert mod.models[0].timeout == timedelta(minutes=1)
    assert mod.models[0].settings.workers == 1
    assert mod.models[0].checks.total_states == 100
    assert len(mod.proofs) == 1
    assert mod.proofs[0].name == "all"
    assert mod.proofs[0].timeout == timedelta(minutes=5)
    assert mod.proofs[0].settings.stretch == 2.0
    assert mod.proofs[0].checks.num_obligations == 10


def test_load_manifest_external_modules_single_string(tmp_path):
    """A single external_modules string is coerced to a list."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    jar = tmp_path / "foo.jar"
    jar.write_text("")  # fake jar

    manifest_text = f"""
modules:
  - path: {spec.name}
    dependencies:
      external_modules: {jar.name}
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].dependencies.external_modules == [jar]


def test_load_manifest_community_modules_typo(tmp_path):
    """'tru' typo for community_modules is accepted."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")

    manifest_text = f"""
modules:
  - path: {spec.name}
    dependencies:
      community_modules: tru
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].dependencies.community_modules is True


def test_load_manifest_workers_auto(tmp_path):
    """workers: auto is parsed correctly."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")

    manifest_text = f"""
modules:
  - path: {spec.name}
    models:
      - name: big
        path: {cfg.name}
        type: explicit
        mode: exhaustive
        settings:
          workers: auto
          max_heap_size: "8G"
        checks:
          success: true
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].models[0].settings.workers == "auto"
    assert m.modules[0].models[0].settings.max_heap_size == "8G"


def test_load_manifest_missing_file_raises(tmp_path):
    """A path that doesn't exist causes a click.UsageError (not a raw ValidationError)."""
    manifest_text = """
modules:
  - path: specs/DoesNotExist.tla
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    with pytest.raises(click.UsageError):
        Manifest.load_manifest(manifest_file)


def test_load_manifest_no_models_no_proofs(tmp_path):
    """A module with only dependencies and no models/proofs is valid."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("")
    jar = tmp_path / "extra.jar"
    jar.write_text("")

    manifest_text = f"""
modules:
  - path: {spec.name}
    dependencies:
      community_modules: true
      external_modules: {jar.name}
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].models == []
    assert m.modules[0].proofs == []
    assert m.modules[0].dependencies.community_modules is True


# ---------------------------------------------------------------------------
# Issue 08 — ActionResult.overall_ok
# ---------------------------------------------------------------------------


def test_overall_ok_is_checks_passed_when_success_false():
    """overall_ok should be True when checks_passed=True even if success=False."""
    r = ActionResult(
        action_type="model",
        name="test",
        module_name="Spec",
        success=False,
        checks_passed=True,
    )
    assert r.overall_ok is True


def test_overall_ok_is_checks_passed_when_both_true():
    """overall_ok should be True when both success and checks_passed are True."""
    r = ActionResult(
        action_type="model",
        name="test",
        module_name="Spec",
        success=True,
        checks_passed=True,
    )
    assert r.overall_ok is True


def test_overall_ok_false_when_checks_failed():
    """overall_ok should be False when checks_passed=False, regardless of success."""
    r = ActionResult(
        action_type="model",
        name="test",
        module_name="Spec",
        success=True,
        checks_passed=False,
    )
    assert r.overall_ok is False


# ---------------------------------------------------------------------------
# Issue 15 — load_manifest error handling
# ---------------------------------------------------------------------------


def test_load_manifest_bad_yaml_raises_usage_error(tmp_path):
    """Invalid YAML should raise click.UsageError, not a raw exception."""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("invalid: yaml: [")

    with pytest.raises(click.UsageError):
        Manifest.load_manifest(manifest_file)


def test_load_manifest_bad_yaml_no_traceback_in_message(tmp_path):
    """The UsageError message should not contain a raw Python traceback."""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("invalid: yaml: [")

    with pytest.raises(click.UsageError) as exc_info:
        Manifest.load_manifest(manifest_file)

    assert "Traceback" not in str(exc_info.value)


def test_load_manifest_non_dict_yaml_raises_usage_error(tmp_path):
    """A YAML list at the top level should raise click.UsageError mentioning 'mapping'."""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("- item1\n- item2\n")

    with pytest.raises(click.UsageError, match="must be a YAML mapping"):
        Manifest.load_manifest(manifest_file)


def test_load_manifest_validation_error_raises_usage_error(tmp_path):
    """A YAML with an invalid/missing path should raise click.UsageError mentioning 'is invalid'."""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("modules:\n  - path: does_not_exist.tla\n")

    with pytest.raises(click.UsageError, match="is invalid"):
        Manifest.load_manifest(manifest_file)


# ---------------------------------------------------------------------------
# Issue 16 — Skipped ActionResult tracking
# ---------------------------------------------------------------------------


def test_skipped_result_has_detail_skipped():
    """An ActionResult with detail='skipped' should have overall_ok=True."""
    r = ActionResult(
        action_type="model",
        name="small",
        module_name="Spec",
        success=True,
        checks_passed=True,
        duration=None,
        detail="skipped",
    )
    assert r.detail == "skipped"
    assert r.overall_ok is True


# ---------------------------------------------------------------------------
# Model.path optional — defaults to <module>.cfg
# ---------------------------------------------------------------------------


def test_model_path_defaults_to_module_cfg(tmp_path):
    """When a model omits 'path', it must default to a sibling .cfg file."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("SPECIFICATION Spec\n")

    manifest_text = f"""
modules:
  - path: {spec.name}
    models:
      - name: default
        checks:
          success: true
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].models[0].path == cfg


def test_model_path_default_missing_cfg_raises(tmp_path):
    """If 'path' is omitted but the implied <module>.cfg doesn't exist, raise."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")

    manifest_text = f"""
modules:
  - path: {spec.name}
    models:
      - name: default
        checks:
          success: true
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    with pytest.raises(click.UsageError):
        Manifest.load_manifest(manifest_file)


def test_model_path_explicit_overrides_default(tmp_path):
    """When 'path' is provided it is used as-is, even when a sibling .cfg exists."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    cfg = tmp_path / "Spec.cfg"
    cfg.write_text("")
    other_cfg = tmp_path / "Other.cfg"
    other_cfg.write_text("")

    manifest_text = f"""
modules:
  - path: {spec.name}
    models:
      - name: other
        path: {other_cfg.name}
        checks:
          success: true
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].models[0].path == other_cfg


# ---------------------------------------------------------------------------
# Proof.path removed — proofs always run against the module .tla file
# ---------------------------------------------------------------------------


def test_proof_has_no_path_field():
    p = Proof(name="all", checks=ProofChecks(success=True))
    assert not hasattr(p, "path") or getattr(p, "path", None) is None


def test_proof_path_in_yaml_is_ignored(tmp_path):
    """A legacy manifest with 'path:' under proofs must load without error
    (the field is now silently ignored)."""
    spec = tmp_path / "Spec.tla"
    spec.write_text("---- MODULE Spec ----\n====\n")
    legacy_proof_file = tmp_path / "Spec_proofs.tla"
    legacy_proof_file.write_text("")

    manifest_text = f"""
modules:
  - path: {spec.name}
    proofs:
      - name: all
        path: {legacy_proof_file.name}
        checks:
          success: true
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    m = Manifest.load_manifest(manifest_file)
    assert m.modules[0].proofs[0].name == "all"


# ---------------------------------------------------------------------------
# ProofChecks: num_omitted / num_unproved
# ---------------------------------------------------------------------------


def test_proof_checks_with_omitted_and_unproved():
    c = ProofChecks(success=True, num_obligations=10, num_omitted=2, num_unproved=1)
    assert c.num_omitted == 2
    assert c.num_unproved == 1


def test_proof_checks_omitted_unproved_default_none():
    c = ProofChecks(success=True)
    assert c.num_omitted is None
    assert c.num_unproved is None


# ---------------------------------------------------------------------------
# _verify_proof_checks — omitted/unproved validation
# ---------------------------------------------------------------------------


class _FakeTLAPMRun:
    def __init__(self, success, num_obligations=0, num_omitted=0, num_unproved=0):
        self.success = success
        self.num_obligations = num_obligations
        self.num_omitted = num_omitted
        self.num_unproved = num_unproved


def _bare_manifest(tmp_path):
    spec = tmp_path / "S.tla"
    spec.write_text("")
    return Manifest(base_path=tmp_path, modules=[Module(path=spec)])


def test_verify_proof_checks_num_omitted_match(tmp_path):
    m = _bare_manifest(tmp_path)
    run = _FakeTLAPMRun(success=True, num_obligations=10, num_omitted=2)
    ok, _ = m._verify_proof_checks(run, ProofChecks(success=True, num_omitted=2))
    assert ok


def test_verify_proof_checks_num_omitted_mismatch(tmp_path):
    m = _bare_manifest(tmp_path)
    run = _FakeTLAPMRun(success=True, num_obligations=10, num_omitted=3)
    ok, detail = m._verify_proof_checks(run, ProofChecks(success=True, num_omitted=2))
    assert not ok
    assert "num_omitted=3" in detail
    assert "expected 2" in detail


def test_verify_proof_checks_num_unproved_mismatch(tmp_path):
    m = _bare_manifest(tmp_path)
    run = _FakeTLAPMRun(success=False, num_unproved=5)
    ok, detail = m._verify_proof_checks(run, ProofChecks(success=False, num_unproved=0))
    assert not ok
    assert "num_unproved=5" in detail


def test_verify_proof_checks_reports_all_mismatches(tmp_path):
    m = _bare_manifest(tmp_path)
    run = _FakeTLAPMRun(success=True, num_obligations=8, num_omitted=1, num_unproved=2)
    checks = ProofChecks(success=True, num_obligations=10, num_omitted=0, num_unproved=0)
    ok, detail = m._verify_proof_checks(run, checks)
    assert not ok
    assert "num_obligations" in detail
    assert "num_omitted" in detail
    assert "num_unproved" in detail
