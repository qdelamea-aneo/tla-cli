"""Manifest run command."""

from pathlib import Path

import rich_click as click

from ..utils import error_handler


@click.command(name="run")
@click.argument(
    "manifest_path",
    metavar="MANIFEST",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@error_handler
def tla_run(manifest_path: Path) -> None:
    """
    Process all modules defined in a manifest file.

    Runs every TLC model check and TLAPS proof check listed in MANIFEST,
    then prints a summary table with the outcome of each action.
    """
    from ..manifest import Manifest

    results = Manifest.load_manifest(manifest_path).process()
    if any(not r.overall_ok for r in results):
        raise SystemExit(1)
