"""Pydantic schema models and result types for manifest processing.

These models represent the structure of a ``manifest.yaml`` file.  They
contain no I/O or tool-invocation logic — see :mod:`.processor` for that.

Manifest YAML format::

    modules:
      - path: specs/MySpec.tla
        dependencies:
          community_modules: true
          external_modules: path/to/extra.jar   # string or list
        models:
          - name: small
            path: specs/MySpec.cfg
            timeout: "0:05:00"
            mode: exhaustive
            settings:
              workers: auto      # int or "auto"
              max_heap_size: 4G
            checks:
              success: true
              total_states: 1234
              distinct_states: 567
              state_depth: 8
        proofs:
          - name: all
            path: specs/MySpec_proofs.tla
            timeout: "0:10:00"
            settings:
              stretch: 2
            checks:
              success: true
              num_obligations: 42
"""

import re
from datetime import timedelta
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Duration parsing helper
# ---------------------------------------------------------------------------

_RE_DURATION = re.compile(r"^(\d+):(\d+):(\d+)$")


def _parse_duration(v) -> Optional[timedelta]:
    """Parse ``"H:MM:SS"`` strings (and pass through ``timedelta`` objects)."""
    if v is None:
        return None
    if isinstance(v, timedelta):
        return v
    if isinstance(v, (int, float)):
        return timedelta(seconds=v)
    if isinstance(v, str):
        m = _RE_DURATION.match(v.strip())
        if m:
            h, minutes, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return timedelta(hours=h, minutes=minutes, seconds=s)
        raise ValueError(f"Cannot parse duration: {v!r} (expected H:MM:SS)")
    raise TypeError(f"Cannot parse duration from type {type(v).__name__}")


# ---------------------------------------------------------------------------
# TLC model-check schema
# ---------------------------------------------------------------------------


class ModelSettings(BaseModel):
    """Runtime settings for a TLC model-checking run.

    Attributes:
        max_heap_size: Maximum JVM heap size (e.g. ``"4G"``).
        workers: Number of TLC worker threads, or ``"auto"`` to use all
            available cores.
    """

    max_heap_size: str = "1G"
    workers: Union[int, Literal["auto"]] = 1


class ModelChecks(BaseModel):
    """Expected outcomes for a TLC model-checking run.

    Attributes:
        success: Whether the model check should succeed.
        total_states: Expected total number of states generated.
        distinct_states: Expected number of distinct states.
        state_depth: Expected maximum BFS depth.
        error_type: Expected error type label when ``success`` is ``False``.
    """

    success: bool
    total_states: Optional[int] = None
    distinct_states: Optional[int] = None
    state_depth: Optional[int] = None
    error_type: Optional[str] = None


class Model(BaseModel):
    """A TLC model-checking configuration.

    Attributes:
        name: Short identifier for the model (e.g. ``"small"``).
        path: Path to the ``.cfg`` model configuration file.
        timeout: Maximum allowed wall-clock duration for the run.
        type: Model type; currently only ``"explicit"`` (TLC) is supported.
        mode: Checking mode: ``"exhaustive"`` (BFS) or ``"simulation"``.
        settings: JVM / worker-thread configuration.
        checks: Expected results to validate after the run.
    """

    name: str
    path: Path
    timeout: Optional[timedelta] = None
    type: Literal["explicit", "symbolic"] = "explicit"
    mode: Literal["exhaustive", "simulation"] = "exhaustive"
    settings: ModelSettings = Field(default_factory=ModelSettings)
    checks: ModelChecks

    @field_validator("timeout", mode="before")
    @classmethod
    def parse_timeout(cls, v):
        return _parse_duration(v)


# ---------------------------------------------------------------------------
# TLAPS proof-check schema
# ---------------------------------------------------------------------------


class ProofSettings(BaseModel):
    """Runtime settings for a TLAPS proof run.

    Attributes:
        stretch: Multiply all backend timeouts by this factor.
    """

    stretch: Optional[float] = None


class ProofChecks(BaseModel):
    """Expected outcomes for a TLAPS proof run.

    Attributes:
        success: Whether all obligations should be proved.
        num_obligations: Expected total number of proof obligations.
    """

    success: bool
    num_obligations: Optional[int] = None


class Proof(BaseModel):
    """A TLAPS proof-checking configuration.

    Attributes:
        name: Short identifier for the proof (e.g. ``"all"``).
        path: Path to the TLA+ proof file.
        timeout: Maximum allowed wall-clock duration for the run.
        settings: Prover runtime settings.
        checks: Expected results to validate after the run.
    """

    name: str
    path: Path
    timeout: Optional[timedelta] = None
    settings: ProofSettings = Field(default_factory=ProofSettings)
    checks: ProofChecks

    @field_validator("timeout", mode="before")
    @classmethod
    def parse_timeout(cls, v):
        return _parse_duration(v)


# ---------------------------------------------------------------------------
# Module schema
# ---------------------------------------------------------------------------


class Dependencies(BaseModel):
    """External dependencies required by a TLA+ module.

    Attributes:
        community_modules: Whether to include the CommunityModules JAR
            in the classpath (and the CommunityModules directory in the
            TLAPS search path).
        external_modules: Additional JAR files or directories.  Accepts
            either a single path (string) or a list of paths.
    """

    community_modules: bool = False
    external_modules: list[Path] = Field(default_factory=list)

    @field_validator("community_modules", mode="before")
    @classmethod
    def coerce_community_modules(cls, v):
        """Accept ``True``, ``"true"``, ``"tru"`` (common typo), etc."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower().startswith("tru")
        return bool(v)

    @field_validator("external_modules", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        """Accept a single path string as well as a list."""
        if v is None:
            return []
        if isinstance(v, (str, Path)):
            return [v]
        return v


class Module(BaseModel):
    """A TLA+ module with its associated models and proofs.

    Attributes:
        path: Path to the TLA+ source file.
        dependencies: External dependencies for this module.
        models: TLC model-checking configurations.
        proofs: TLAPS proof-checking configurations.
    """

    path: Path
    dependencies: Dependencies = Field(default_factory=Dependencies)
    models: list[Model] = Field(default_factory=list)
    proofs: list[Proof] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class ActionResult:
    """Result of a single manifest action (model check or proof check).

    Attributes:
        action_type: ``"model"`` or ``"proof"``.
        name: Action name (e.g. ``"small"``).
        module_name: Short module name (stem of the module path).
        success: Whether the action succeeded.
        checks_passed: Whether the expected checks passed.
        duration: Wall-clock duration, if available.
        detail: Short human-readable outcome string.
    """

    def __init__(
        self,
        action_type: str,
        name: str,
        module_name: str,
        success: bool,
        checks_passed: bool,
        duration: Optional[timedelta] = None,
        detail: str = "",
    ) -> None:
        self.action_type = action_type
        self.name = name
        self.module_name = module_name
        self.success = success
        self.checks_passed = checks_passed
        self.duration = duration
        self.detail = detail

    @property
    def overall_ok(self) -> bool:
        return self.success and self.checks_passed

    def model_dump(self) -> dict:
        return {
            "action_type": self.action_type,
            "name": self.name,
            "module_name": self.module_name,
            "success": self.success,
            "checks_passed": self.checks_passed,
            "duration": self.duration,
            "detail": self.detail,
        }
