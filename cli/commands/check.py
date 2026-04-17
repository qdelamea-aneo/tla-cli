"""TLC model-checking and simulation commands."""

from pathlib import Path
from typing import Optional

import rich_click as click

from ..constants import CONSOLE, tlc
from ..utils import error_handler


def _common_tlc_options(func):
    """Decorator that attaches options shared by model-check and simulate."""
    func = click.option(
        "--workers", "-w",
        metavar="NUM_WORKERS",
        type=int,
        default=1,
        show_default=True,
        help="Number of worker threads for TLC.",
    )(func)
    func = click.option(
        "--max-heap-size",
        metavar="SIZE",
        type=str,
        default="4G",
        show_default=True,
        help="Maximum heap size for the JVM (e.g., 4G, 512M).",
    )(func)
    func = click.option(
        "--community-modules/--no-community-modules",
        default=True,
        show_default=True,
        help="Whether to include CommunityModules in the classpath.",
    )(func)
    func = click.option(
        "--external-module",
        metavar="MODULE_PATH",
        type=click.Path(
            exists=True, dir_okay=True, file_okay=True, resolve_path=True, path_type=Path
        ),
        multiple=True,
        help="Additional external TLA+ modules or JAR files to include in the classpath.",
    )(func)
    func = click.option(
        "--model-path",
        metavar="MODEL_PATH",
        type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
        help=(
            "Path to the TLC configuration file (.cfg). "
            "If not provided, it is assumed to be alongside the module file "
            "with a .cfg extension."
        ),
    )(func)
    return func


@click.command(name="model-check")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@_common_tlc_options
@click.option(
    "--save-states", "-s",
    is_flag=True,
    help="Export the reachable state space as a Graphviz .dot file.",
)
@click.option(
    "--export-json", "-j",
    is_flag=True,
    help="Export the reachable state space as a JSON file.",
)
@click.option(
    "--checkpoint-dir",
    metavar="DIR",
    type=click.Path(dir_okay=True, file_okay=False, resolve_path=True, path_type=Path),
    default=None,
    help=(
        "Directory for TLC metadata and checkpoints (-metadir). "
        "When an existing checkpoint is present TLC resumes automatically."
    ),
)
@click.option(
    "--checkpoint-interval",
    metavar="MINUTES",
    type=int,
    default=None,
    help="Save a checkpoint every MINUTES minutes. Requires --checkpoint-dir.",
)
@click.option(
    "--coverage",
    metavar="MINUTES",
    type=int,
    default=None,
    help=(
        "Report action and property coverage statistics every MINUTES minutes "
        "(use 0 to report once at the end of the run)."
    ),
)
@click.option(
    "--explain",
    is_flag=True,
    default=False,
    help=(
        "On failure, send the TLC log to an LLM and stream a human-readable "
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
@error_handler
def tla_model_check(
    module_path: Path,
    model_path: Optional[Path],
    workers: int,
    max_heap_size: str,
    community_modules: bool,
    external_module: list[Path],
    save_states: bool,
    export_json: bool,
    checkpoint_dir: Optional[Path],
    checkpoint_interval: Optional[int],
    coverage: Optional[int],
    explain: bool,
    llm_backend: str,
) -> None:
    """
    Run the TLC model checker on a TLA+ module file.

    Performs exhaustive breadth-first state-space exploration.  Use the
    ``simulate`` command for random trace exploration instead.
    """
    for ext_module in external_module:
        if ext_module.is_file() and ext_module.suffix != ".jar":
            raise click.BadArgumentUsage(
                f"External module '{ext_module}' must be a .jar file."
            )

    if checkpoint_interval is not None and checkpoint_dir is None:
        raise click.UsageError("--checkpoint-interval requires --checkpoint-dir.")

    model_path = model_path or module_path.with_suffix(".cfg")
    run = tlc.start(
        module_path,
        model_path,
        workers=workers,
        max_heap_size=max_heap_size,
        community_modules=community_modules,
        external_modules=list(external_module),
        save_states=save_states,
        export_json=export_json,
        checkpoint_dir=checkpoint_dir,
        checkpoint_interval=checkpoint_interval,
        coverage_interval=coverage,
    )

    if explain and not run.success and run.log_file and run.log_file.exists():
        from ..tools.llm import explain_tlc_error
        explain_tlc_error(run.log_file.read_text(), CONSOLE, backend_name=llm_backend, tlc_run=run)


@click.command(name="simulate")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@_common_tlc_options
@click.option(
    "--depth", "-d",
    metavar="N",
    type=int,
    default=None,
    help="Maximum depth of each simulated trace (default: 100).",
)
@click.option(
    "--seed",
    metavar="N",
    type=int,
    default=None,
    help="Random seed for reproducible simulation.",
)
@click.option(
    "--num-traces",
    metavar="N",
    type=int,
    default=None,
    help="Stop after simulating N traces (default: run indefinitely).",
)
@click.option(
    "--explain",
    is_flag=True,
    default=False,
    help=(
        "On failure, send the TLC log to an LLM and stream a human-readable "
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
@error_handler
def tla_simulate(
    module_path: Path,
    model_path: Optional[Path],
    workers: int,
    max_heap_size: str,
    community_modules: bool,
    external_module: list[Path],
    depth: Optional[int],
    seed: Optional[int],
    num_traces: Optional[int],
    explain: bool,
    llm_backend: str,
) -> None:
    """
    Run TLC in simulation mode on a TLA+ module file.

    Instead of exhaustive state-space search, TLC explores random traces up to
    a given depth.  Useful for quickly finding bugs in large or infinite-state
    models where exhaustive checking is not feasible.
    """
    for ext_module in external_module:
        if ext_module.is_file() and ext_module.suffix != ".jar":
            raise click.BadArgumentUsage(
                f"External module '{ext_module}' must be a .jar file."
            )

    model_path = model_path or module_path.with_suffix(".cfg")
    run = tlc.simulate(
        module_path,
        model_path,
        workers=workers,
        max_heap_size=max_heap_size,
        community_modules=community_modules,
        external_modules=list(external_module),
        depth=depth,
        seed=seed,
        num_traces=num_traces,
    )

    if explain and not run.success and run.log_file and run.log_file.exists():
        from ..tools.llm import explain_tlc_error
        explain_tlc_error(run.log_file.read_text(), CONSOLE, backend_name=llm_backend, tlc_run=run)
