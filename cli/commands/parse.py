"""SANY parse command."""

from pathlib import Path

import rich_click as click

from ..constants import sany
from ..utils import error_handler


@click.command(name="parse")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@click.option(
    "--community-modules/--no-community-modules",
    default=True,
    show_default=True,
    help="Whether to include CommunityModules in the classpath.",
)
@click.option(
    "--external-module",
    metavar="MODULE_PATH",
    type=click.Path(
        exists=True, dir_okay=True, file_okay=True, resolve_path=True, path_type=Path
    ),
    multiple=True,
    help="Additional external TLA+ modules or JAR files to include in the classpath.",
)
@error_handler
def tla_parse(
    module_path: Path,
    community_modules: bool,
    external_module: tuple[Path, ...],
) -> None:
    """
    Parse and type-check a TLA+ module with SANY.

    Runs the SANY parser and semantic analyser from tla2tools.jar on the
    given module file.  Exits with a non-zero status when SANY reports any
    errors.
    """
    if not sany.is_available():
        raise click.ClickException(
            "tla2tools is not installed.  Run 'tla package install tla2tools'."
        )

    run = sany.parse(
        module_path,
        community_modules=community_modules,
        external_modules=list(external_module),
    )

    if not run.success:
        raise SystemExit(1)
