"""TLAPS proof-check command."""

from datetime import timedelta
from pathlib import Path
from typing import Optional

import rich_click as click

from ..constants import tlapm
from ..utils import error_handler


@click.command(name="proof-check")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@click.option(
    "--stretch",
    metavar="FACTOR",
    type=float,
    default=None,
    help="Multiply all backend timeouts by FACTOR (passed as --stretch to tlapm).",
)
@click.option(
    "--community-modules/--no-community-modules",
    default=True,
    show_default=True,
    help="Whether to add the CommunityModules directory to tlapm's search path (-I).",
)
@click.option(
    "--external-module",
    metavar="MODULE_PATH",
    type=click.Path(
        exists=True, dir_okay=True, file_okay=True, resolve_path=True, path_type=Path
    ),
    multiple=True,
    help=(
        "Additional TLA+ module file or directory to add to tlapm's search "
        "path (-I).  Repeat for multiple entries."
    ),
)
@click.option(
    "--timeout",
    metavar="SECONDS",
    type=int,
    default=None,
    help="Kill tlapm after SECONDS seconds.",
)
@error_handler
def tla_proof_check(
    module_path: Path,
    stretch: Optional[float],
    community_modules: bool,
    external_module: tuple[Path, ...],
    timeout: Optional[int],
) -> None:
    """
    Check TLA+ proofs with TLAPS (tlapm).

    Runs tlapm in toolbox mode on the given proof file and displays
    per-obligation proving progress.  Exits with a non-zero status when
    any obligation fails to be proved.
    """
    if not tlapm.is_available():
        raise click.ClickException(
            "tlapm is not installed.  Install it and re-run."
        )

    # tlapm uses -I <dir> for module search paths. Resolve each entry to a
    # directory: use the path as-is when it is a directory, or its parent when
    # the user passes an individual .tla file.
    include_dirs = [p if p.is_dir() else p.parent for p in external_module]

    timeout_td = timedelta(seconds=timeout) if timeout is not None else None
    run = tlapm.prove(
        module_path,
        stretch=stretch,
        community_modules=community_modules,
        include_dirs=include_dirs,
        timeout=timeout_td,
    )

    if not run.success:
        raise SystemExit(1)
