"""Manifest run command."""

import json
import sys

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import rich_click as click

from ..utils import error_handler

if TYPE_CHECKING:
    from ..cli import AppContext


@click.command(name="run")
@click.argument(
    "manifest_path",
    metavar="MANIFEST",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@click.option(
    "--filter",
    "-f",
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
    "--workers",
    "-w",
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
@click.option(
    "--no-progress",
    "no_progress",
    is_flag=True,
    default=False,
    help=(
        "Disable the interactive live displays inside each tool run.  "
        "Progress updates are printed as plain lines instead."
    ),
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help=(
        "Output format.  'json' emits a JSON array of action results to stdout "
        "and suppresses all Rich panels."
    ),
)
@click.pass_obj
@error_handler
def tla_run(
    app: "AppContext",
    manifest_path: Path,
    filters: tuple[str, ...],
    workers: Optional[int],
    max_heap_size: Optional[str],
    skip_passed: bool,
    no_progress: bool,
    output_format: str,
) -> None:
    """
    Process all modules defined in a manifest file.

    Runs every TLC model check and TLAPS proof check listed in MANIFEST,
    then prints a summary table with the outcome of each action.
    Use --filter to run only a subset of actions.
    """
    from ..manifest import Manifest

    use_json = output_format == "json"
    results = Manifest.load_manifest(manifest_path).process(
        tlc=app.tlc,
        tlapm=app.tlapm,
        filters=list(filters) if filters else None,
        workers_override=workers,
        max_heap_override=max_heap_size,
        skip_passed=skip_passed,
        interactive=not (no_progress or use_json),
        silent=use_json,
        cache_dir=app.cache_dir,
    )

    if use_json:
        json.dump(
            [r.model_dump() for r in results],
            sys.stdout,
            indent=2,
            default=str,
        )
        sys.stdout.write("\n")

    if any(not r.overall_ok for r in results):
        raise SystemExit(1)
