"""Manifest loading and processing orchestration.

This module defines :class:`Manifest`, the top-level object that loads a
``manifest.yaml`` file, resolves all relative paths, and drives the
sequential execution of TLC model checks and TLAPS proof checks for every
listed module.
"""

from datetime import timedelta
from pathlib import Path
from typing import Optional, Union
from typing_extensions import Self

import yaml

from pydantic import BaseModel, DirectoryPath, Field, model_validator
from rich.table import Table

from ..constants import CONSOLE, VALID, CROSS, tlc, tlapm
from .models import (
    ActionResult,
    Dependencies,
    Model,
    ModelChecks,
    Module,
    Proof,
    ProofChecks,
)


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
            if not (module.models or module.proofs):
                continue

            CONSOLE.print()
            CONSOLE.print(f"[bold cyan]Module:[/bold cyan] {module.path.name}")

            for model in module.models:
                results.append(self._run_model(module, model))

            for proof in module.proofs:
                results.append(self._run_proof(module, proof))

        self._print_summary(results)
        return results

    # ------------------------------------------------------------------
    # Internal: model check
    # ------------------------------------------------------------------

    def _run_model(self, module: Module, model: Model) -> ActionResult:
        CONSOLE.print(f"  [dim]▸ Model:[/dim] {model.name}")

        workers_arg: Union[int, str] = (
            "auto" if model.settings.workers == "auto" else int(model.settings.workers)
        )

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
            ``(passed, detail_message)``
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
            include_dirs = [
                p if p.is_dir() else p.parent
                for p in module.dependencies.external_modules
            ]
            tlapm_run = tlapm.prove(
                proof.path,
                stretch=proof.settings.stretch,
                community_modules=module.dependencies.community_modules,
                include_dirs=include_dirs,
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
            table.add_row(r.module_name, r.name, r.action_type, icon, dur, detail)

        CONSOLE.print(table)
