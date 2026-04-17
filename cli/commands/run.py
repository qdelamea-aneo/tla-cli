"""Manifest run command."""

from pathlib import Path
from typing import Optional

import rich_click as click

from ..utils import error_handler


@click.command(name="run")
@click.argument(
    "manifest_path",
    metavar="MANIFEST",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@click.option(
    "--filter", "-f",
    "filters",
    metavar="SPEC",
    multiple=True,
    help=(
        "Run only matching actions.  SPEC is either a module stem "
        "(e.g. 'MyModule') or 'MODULE/ACTION' for a single action.  "
        "Repeat for multiple filters."
    ),
)
@click.option(
    "--workers", "-w",
    metavar="N",
    type=int,
    default=None,
    help="Override the worker count for every model check in this run.",
)
@click.option(
    "--max-heap-size",
    metavar="SIZE",
    type=str,
    default=None,
    help="Override the JVM heap size for every model check (e.g. 4G, 512M).",
)
@click.option(
    "--skip-passed",
    is_flag=True,
    default=False,
    help=(
        "Skip actions that passed on their last run.  Pass/fail state is "
        "cached in .tla-run-cache.json next to the manifest file."
    ),
)
@error_handler
def tla_run(
    manifest_path: Path,
    filters: tuple[str, ...],
    workers: Optional[int],
    max_heap_size: Optional[str],
    skip_passed: bool,
) -> None:
    """
    Process all modules defined in a manifest file.

    Runs every TLC model check and TLAPS proof check listed in MANIFEST,
    then prints a summary table with the outcome of each action.
    Use --filter to run only a subset of actions.
    """
    from ..manifest import Manifest

    results = Manifest.load_manifest(manifest_path).process(
        filters=list(filters) if filters else None,
        workers_override=workers,
        max_heap_override=max_heap_size,
        skip_passed=skip_passed,
    )
    if any(not r.overall_ok for r in results):
        raise SystemExit(1)
