"""Unit tests for the manifest model classes.

Tests cover:
- YAML loading and parsing of all field types
- Duration (timedelta) coercion from "H:MM:SS" strings
- Dependencies.community_modules coercion (typo tolerance)
- Dependencies.external_modules coercion (single string → list)
- ModelSettings.workers "auto" support
- Proof and Model check field validation
- Path resolution via model_validator
"""

import pytest

from datetime import timedelta
from pathlib import Path

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
from tla_cli.manifest.models import _parse_duration


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
    """A path that doesn't exist causes a ValidationError."""
    manifest_text = """
modules:
  - path: specs/DoesNotExist.tla
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_text)

    with pytest.raises(ValidationError):
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
