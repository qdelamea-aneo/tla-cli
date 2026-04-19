"""SANY parse command."""

import json
import sys

from pathlib import Path

import rich_click as click

from ..constants import CONSOLE, sany
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
        "On failure, send the SANY log to an LLM and stream a human-readable "
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
@error_handler
def tla_parse(
    module_path: Path,
    community_modules: bool,
    external_module: tuple[Path, ...],
    no_progress: bool,
    explain: bool,
    llm_backend: str,
    output_format: str,
) -> None:
    """
    Parse a TLA+ module with SANY.

    Runs the SANY parser and semantic analyser from tla2tools.jar on the
    given module file.  Exits with a non-zero status when SANY reports any
    errors.
    """
    use_json = output_format == "json"
    run = sany.parse(
        module_path,
        community_modules=community_modules,
        external_modules=list(external_module),
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
        from ..wrappers.llm import explain_sany_error

        explain_sany_error(run.log_file.read_text(), CONSOLE, backend_name=llm_backend)

    if not run.success:
        raise SystemExit(1)
