"""Manifest model definitions and processing logic.

This module defines the Pydantic models that represent a processing manifest
(``manifest.yaml``) and the :class:`Manifest` class that orchestrates running
TLC model checks and TLAPS proof checks for all listed modules.

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
            type: explicit
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

import os
import re

from datetime import timedelta
from pathlib import Path
from typing import Optional, Union, Literal
from typing_extensions import Self

import yaml

from pydantic import BaseModel, DirectoryPath, Field, field_validator, model_validator

from .constants import CONSOLE, VALID, CROSS, tlc, tlapm, TOOLS_DIR


# ---------------------------------------------------------------------------
# Shared helpers
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


# ---------------------------------------------------------------------------
# Sub-models
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
# Result types
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


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class Manifest(BaseModel):
    """The top-level processing manifest.

    Attributes:
        base_path: Directory containing the manifest file; used to
            resolve all relative paths.
        modules: List of modules to process.
    """

    base_path: DirectoryPath
    modules: list[Module]

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load_manifest(cls, path: Path) -> "Manifest":
        """Load a manifest from a YAML file.

        Args:
            path: Path to the ``manifest.yaml`` file.

        Returns:
            A validated :class:`Manifest` instance.
        """
        with path.open("r") as f:
            data = yaml.safe_load(f)
        return cls(base_path=path.parent, **data)

    # ------------------------------------------------------------------
    # Path validation
    # ------------------------------------------------------------------

    def _resolve(self, p: Path) -> Path:
        """Return the absolute path of *p*, resolved relative to base_path."""
        if not p.is_absolute():
            p = self.base_path / p
        if not p.exists():
            raise ValueError(f"File not found: {p}")
        return p

    @model_validator(mode="after")
    def resolve_paths(self) -> Self:
        """Resolve all relative paths to absolute paths."""
        for module in self.modules:
            module.path = self._resolve(module.path)
            module.dependencies.external_modules = [
                self._resolve(ep)
                for ep in module.dependencies.external_modules
            ]
            for model in module.models:
                model.path = self._resolve(model.path)
            for proof in module.proofs:
                proof.path = self._resolve(proof.path)
        return self

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self) -> list[ActionResult]:
        """Process all modules defined in the manifest.

        Runs each model check and proof check in sequence, printing a
        section header for each module and a summary table at the end.

        Returns:
            List of :class:`ActionResult` objects, one per action.
        """
        results: list[ActionResult] = []

        CONSOLE.print()
        CONSOLE.rule("[bold]Manifest processing[/bold]")

        for module in self.modules:
            has_actions = bool(module.models or module.proofs)
            if not has_actions:
                continue

            CONSOLE.print()
            CONSOLE.print(f"[bold cyan]Module:[/bold cyan] {module.path.name}")

            for model in module.models:
                result = self._run_model(module, model)
                results.append(result)

            for proof in module.proofs:
                result = self._run_proof(module, proof)
                results.append(result)

        self._print_summary(results)
        return results

    # ------------------------------------------------------------------
    # Internal: model check
    # ------------------------------------------------------------------

    def _run_model(self, module: Module, model: Model) -> ActionResult:
        CONSOLE.print(f"  [dim]▸ Model:[/dim] {model.name}")

        workers: Union[int, str] = model.settings.workers
        # Resolve "auto" → actual CPU count for the TLC wrapper
        if workers == "auto":
            workers_arg = "auto"
        else:
            workers_arg = int(workers)

        try:
            tlc_run = tlc.start(
                module.path,
                model.path,
                workers=workers_arg,
                max_heap_size=model.settings.max_heap_size,
                community_modules=module.dependencies.community_modules,
                external_modules=module.dependencies.external_modules,
            )
        except Exception as exc:
            CONSOLE.print(f"    [red]Error running TLC: {exc}[/red]")
            return ActionResult(
                action_type="model",
                name=model.name,
                module_name=module.path.stem,
                success=False,
                checks_passed=False,
                detail=str(exc),
            )

        checks_passed, detail = self._verify_model_checks(tlc_run, model.checks)
        if not checks_passed:
            CONSOLE.print(f"    [yellow]Check mismatch: {detail}[/yellow]")

        return ActionResult(
            action_type="model",
            name=model.name,
            module_name=module.path.stem,
            success=bool(tlc_run.success),
            checks_passed=checks_passed,
            duration=tlc_run.duration,
            detail=detail,
        )

    def _verify_model_checks(self, tlc_run, checks: ModelChecks) -> tuple[bool, str]:
        """Compare TLC run results against expected checks.

        Returns:
            (passed, detail_message)
        """
        if tlc_run.success != checks.success:
            return False, f"success={tlc_run.success} (expected {checks.success})"

        if checks.success:
            mismatches: list[str] = []
            if checks.total_states is not None and tlc_run.total_states != checks.total_states:
                mismatches.append(
                    f"total_states={tlc_run.total_states} (expected {checks.total_states})"
                )
            if checks.distinct_states is not None and tlc_run.total_distinct_states != checks.distinct_states:
                mismatches.append(
                    f"distinct_states={tlc_run.total_distinct_states} (expected {checks.distinct_states})"
                )
            if checks.state_depth is not None and tlc_run.state_depth != checks.state_depth:
                mismatches.append(
                    f"state_depth={tlc_run.state_depth} (expected {checks.state_depth})"
                )
            if mismatches:
                return False, "; ".join(mismatches)
        else:
            if checks.error_type is not None and tlc_run.error_type != checks.error_type:
                return False, (
                    f"error_type={tlc_run.error_type!r} (expected {checks.error_type!r})"
                )

        return True, "ok"

    # ------------------------------------------------------------------
    # Internal: proof check
    # ------------------------------------------------------------------

    def _run_proof(self, module: Module, proof: Proof) -> ActionResult:
        CONSOLE.print(f"  [dim]▸ Proof:[/dim] {proof.name}")

        if not tlapm.is_available():
            CONSOLE.print("    [yellow]tlapm is not installed — skipping proof.[/yellow]")
            return ActionResult(
                action_type="proof",
                name=proof.name,
                module_name=module.path.stem,
                success=False,
                checks_passed=False,
                detail="tlapm not available",
            )

        try:
            tlapm_run = tlapm.prove(
                proof.path,
                stretch=proof.settings.stretch,
                community_modules=module.dependencies.community_modules,
                timeout=proof.timeout,
            )
        except Exception as exc:
            CONSOLE.print(f"    [red]Error running tlapm: {exc}[/red]")
            return ActionResult(
                action_type="proof",
                name=proof.name,
                module_name=module.path.stem,
                success=False,
                checks_passed=False,
                detail=str(exc),
            )

        checks_passed, detail = self._verify_proof_checks(tlapm_run, proof.checks)
        if not checks_passed:
            CONSOLE.print(f"    [yellow]Check mismatch: {detail}[/yellow]")

        return ActionResult(
            action_type="proof",
            name=proof.name,
            module_name=module.path.stem,
            success=bool(tlapm_run.success),
            checks_passed=checks_passed,
            duration=tlapm_run.duration,
            detail=detail,
        )

    def _verify_proof_checks(self, tlapm_run, checks: ProofChecks) -> tuple[bool, str]:
        """Compare tlapm run results against expected checks."""
        if tlapm_run.success != checks.success:
            return False, f"success={tlapm_run.success} (expected {checks.success})"

        if checks.num_obligations is not None:
            actual = tlapm_run.num_obligations
            if actual != checks.num_obligations:
                return False, (
                    f"num_obligations={actual} (expected {checks.num_obligations})"
                )

        return True, "ok"

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------

    def _print_summary(self, results: list[ActionResult]) -> None:
        from rich.table import Table

        CONSOLE.print()
        CONSOLE.rule("[bold]Summary[/bold]")
        CONSOLE.print()

        if not results:
            CONSOLE.print("[dim]No actions were processed.[/dim]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Module", no_wrap=True)
        table.add_column("Action", no_wrap=True)
        table.add_column("Type", justify="center")
        table.add_column("Result", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Detail")

        for r in results:
            icon = VALID if r.overall_ok else CROSS
            dur = f"{r.duration.total_seconds():.1f}s" if r.duration else "—"
            detail = "" if r.detail == "ok" else r.detail
            table.add_row(
                r.module_name,
                r.name,
                r.action_type,
                icon,
                dur,
                detail,
            )

        CONSOLE.print(table)
