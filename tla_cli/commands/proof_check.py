"""TLAPS proof-check command."""

import json
import sys

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import rich_click as click

from ..utils import CONSOLE, error_handler

if TYPE_CHECKING:
    from ..cli import AppContext


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
@click.option(
    "--no-progress",
    "no_progress",
    is_flag=True,
    default=False,
    help=(
        "Disable the interactive live display.  Each progress update is "
        "printed as a plain line instead."
    ),
)
@click.option(
    "--explain",
    is_flag=True,
    default=False,
    help=(
        "On failure, send the tlapm log to an LLM and stream a human-readable "
        "explanation to the terminal. Use --llm-backend to select the model."
    ),
)
@click.option(
    "--llm-backend",
    type=click.Choice(["claude", "openai", "gemini", "mistral"], case_sensitive=False),
    default="claude",
    show_default=True,
    help="LLM backend to use with --explain.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format: 'text' for the default Rich display, 'json' for machine-readable output.",
)
@click.pass_obj
@error_handler
def tla_proof_check(
    app: "AppContext",
    module_path: Path,
    stretch: Optional[float],
    community_modules: bool,
    external_module: tuple[Path, ...],
    timeout: Optional[int],
    no_progress: bool,
    explain: bool,
    llm_backend: str,
    output_format: str,
) -> None:
    """
    Check TLA+ proofs with TLAPS (tlapm).

    Runs tlapm in toolbox mode on the given proof file and displays
    per-obligation proving progress.  Exits with a non-zero status when
    any obligation fails to be proved.
    """
    for p in external_module:
        if p.is_file() and p.suffix == ".jar":
            raise click.BadArgumentUsage(
                f"'{p.name}' is a JAR file. tlapm does not use a Java classpath; "
                "pass a .tla file or a directory instead."
            )

    if not app.tlapm.is_available():
        raise click.ClickException(
            "tlapm is not bundled with this version of tla-cli."
        )

    include_dirs = [p if p.is_dir() else p.parent for p in external_module]

    use_json = output_format == "json"
    timeout_td = timedelta(seconds=timeout) if timeout is not None else None
    run = app.tlapm.prove(
        module_path,
        stretch=stretch,
        community_modules=community_modules,
        include_dirs=include_dirs,
        timeout=timeout_td,
        interactive=not (no_progress or use_json),
        silent=use_json,
    )

    if use_json:
        json.dump(run.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        if not run.success:
            raise SystemExit(1)
        return

    if explain and not run.success and run.log_file and run.log_file.exists():
        from ..wrappers.llm import explain_tlapm_error

        explain_tlapm_error(run.log_file.read_text(), CONSOLE, backend_name=llm_backend)

    if not run.success:
        raise SystemExit(1)
