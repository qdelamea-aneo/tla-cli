import os
import re

import rich_click as click

from pathlib import Path
from typing import Optional

from packaging.version import parse as parse_version
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.spinner import Spinner
from rich.text import Text

from .constants import (
    CONSOLE,
    VALID,
    CROSS,
    WORKDIR,
    TOOLS_DIR,
    UNCHANGED,
    tla2tools,
    community_modules,
    tlc,
    tlapm,
    sany,
    repl,
)
from .utils import AliasedGroup, error_handler


# Create a mapping for faster lookup
pkg_map = {p.name: p for p in [tla2tools, community_modules]}


def _show_vibecode_warning() -> None:
    """Print a warning panel before starting the REPL.

    The panel warns users that this CLI was AI-generated and may contain bugs.
    It is suppressed when the environment variable ``TLA_NO_VIBECODE_WARNING``
    is set to any non-empty value.
    """
    if os.environ.get("TLA_NO_VIBECODE_WARNING"):
        return

    content = Text.assemble(
        ("⚠  This CLI is ", "bold yellow"),
        ("vibecoded", "bold yellow underline"),
        (" — generated mostly by an AI.\n", "bold yellow"),
        "\n",
        ("It may contain bugs, produce incorrect output, or behave\n"
         "unexpectedly. ", ""),
        ("Treat all results with appropriate scepticism\n"
         "and verify against the raw TLC output when in doubt.", "dim"),
        "\n\n",
        ("To suppress this warning: ", "dim"),
        ("export TLA_NO_VIBECODE_WARNING=1", "bold cyan"),
    )
    CONSOLE.print(
        Panel(
            content,
            title="[bold yellow]Experimental CLI[/bold yellow]",
            border_style="yellow",
            expand=False,
            padding=(1, 2),
        )
    )
    CONSOLE.print()


@click.group(
    name="tla",
    cls=AliasedGroup,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "auto_envvar_prefix": "TLA_",
    },
    invoke_without_command=True,
)
@click.version_option(version="0.1.0", prog_name="tla-cli")
@click.option(
    "--manifest",
    "-m",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
    help="Path to a manifest file defining TLA+ modules processing.",
)
@click.pass_context
@error_handler
def cli(ctx: click.Context, manifest: Path) -> None:
    """
    Command-line tool to simplify working with TLA+.
    """
    WORKDIR.mkdir(exist_ok=True)
    TOOLS_DIR.mkdir(exist_ok=True)

    if ctx.invoked_subcommand is None:
        if manifest is None and repl.is_available():
            _show_vibecode_warning()
            repl.start()
        elif manifest is not None:
            from .models import Manifest

            manifest_obj = Manifest.load_manifest(manifest)
            manifest_obj.process()
        else:
            click.echo(ctx.get_help())


@cli.group(name="package")
def tla_package() -> None:
    """Commands for managing TLA+ tool packages."""
    pass


@tla_package.command(name="list")
def tla_package_list() -> None:
    """
    Display the installation status of TLA+ tool packages.
    """
    table = Table(title="Package Installation Summary")
    table.add_column("Name", no_wrap=True, justify="center")
    table.add_column("Installed", justify="center")
    table.add_column("Version", justify="center")
    table.add_column("Up-to-date", justify="center")

    for pkg in pkg_map.values():
        if pkg.is_installed:
            table.add_row(
                pkg.name,
                VALID,
                str(pkg.current_version),
                VALID if pkg.is_up_to_date else CROSS,
            )
        else:
            table.add_row(pkg.name, CROSS, "-", "-")

    CONSOLE.print(table)


@tla_package.command(name="install")
@click.argument(
    "pkg_specs",
    metavar="PACKAGE_SPEC",
    nargs=-1,
    type=str,
)
@error_handler
def tla_package_install(pkg_specs: tuple[str, ...]) -> None:
    """
    Install one or more TLA+ tool packages and their dependencies.

    PACKAGE_SPEC format: name or name==version (e.g. tla2tools==1.5.7)

    When no PACKAGE_SPEC is given, all known packages are installed.
    """
    if not pkg_specs:
        pkg_specs = tuple(pkg_map.keys())
    spec_pattern = r"^([a-zA-Z0-9_-]+)(?:==([vV]?\d+\.\d+\.\d+))?$"
    pkgs_to_install = []

    for spec in pkg_specs:
        match = re.match(spec_pattern, spec)
        if not match:
            raise click.BadArgumentUsage(f"Invalid package specifier format: '{spec}'.")

        pkg_name, version_str = match.groups()
        pkg = pkg_map.get(pkg_name)

        if pkg is None:
            raise click.BadArgumentUsage(f"Unknown package: '{pkg_name}'")

        # Determine version to install
        version = parse_version(version_str) if version_str else pkg.latest_version
        if not pkg.version_exists(version):
            raise click.BadArgumentUsage(
                f"Invalid version for package '{pkg_name}': '{version}'."
            )

        pkgs_to_install.append((pkg, version))

    for pkg, version in pkgs_to_install:
        with Live(
            Spinner("dots", text=f"Installing {pkg.name} (version {version})..."),
            console=CONSOLE,
            refresh_per_second=10,
        ) as live:
            if pkg.is_installed:
                live.update(f"{UNCHANGED} {pkg.name} is already installed.")
                continue
            try:
                pkg.install(version)
                live.update(f"{VALID} Installed {pkg.name} (version {version}).")
            except RuntimeError:
                live.update(f"{CROSS} Failed to install {pkg.name}.")
                raise


@tla_package.command(name="upgrade")
@click.argument(
    "pkg_names",
    metavar="PACKAGE_NAME",
    nargs=-1,
    type=str,
)
@error_handler
def tla_package_upgrade(pkg_names: tuple[str, ...]) -> None:
    """
    Upgrade specified TLA+ tool packages to their latest versions.

    When no PACKAGE_NAME is given, all installed packages are upgraded.
    """
    if not pkg_names:
        pkg_names = tuple(pkg_map.keys())
    pkgs_to_upgrade = []

    for pkg_name in pkg_names:
        pkg = pkg_map.get(pkg_name)
        if pkg is None:
            raise click.BadArgumentUsage(f"Unknown package: '{pkg_name}'")
        pkgs_to_upgrade.append(pkg)

    for pkg in pkgs_to_upgrade:
        with Live(
            Spinner(
                "dots", text=f"Upgrading {pkg.name} to version {pkg.latest_version}..."
            ),
            console=CONSOLE,
            refresh_per_second=10,
        ) as live:
            if pkg.is_up_to_date:
                live.update(f"{UNCHANGED} {pkg.name} is already up to date.")
                continue
            try:
                pkg.upgrade()
                live.update(
                    f"{VALID} Upgraded {pkg.name} to version {pkg.latest_version}."
                )
            except RuntimeError:
                live.update(f"{CROSS} Failed to upgrade {pkg.name}.")
                raise


@tla_package.command(name="uninstall")
@click.argument(
    "pkg_names",
    metavar="PACKAGE_NAME",
    nargs=-1,
    type=str,
)
@error_handler
def tla_package_uninstall(pkg_names: tuple[str, ...]) -> None:
    """
    Uninstall one or more installed TLA+ tool packages.

    When no PACKAGE_NAME is given, all installed packages are uninstalled.
    """
    if not pkg_names:
        pkg_names = tuple(pkg_map.keys())
    pkgs_to_uninstall = []

    for pkg_name in pkg_names:
        pkg = pkg_map.get(pkg_name)
        if pkg is None:
            raise click.BadArgumentUsage(f"Unknown package: '{pkg_name}'")
        pkgs_to_uninstall.append(pkg)

    for pkg in pkgs_to_uninstall:
        with Live(
            Spinner("dots", text=f"Uninstalling {pkg.name}..."),
            console=CONSOLE,
            refresh_per_second=10,
        ) as live:
            if not pkg.is_installed:
                live.update(f"{UNCHANGED} {pkg.name} is not currently installed.")
                continue
            try:
                pkg.uninstall()
                live.update(f"{VALID} Uninstalled {pkg.name}.")
            except RuntimeError:
                live.update(f"{CROSS} Failed to uninstall {pkg.name}.")
                raise


# ---------------------------------------------------------------------------
# Shared option factories (avoid copy-paste between model-check and simulate)
# ---------------------------------------------------------------------------

def _common_tlc_options(func):
    """Decorator that attaches options shared by model-check and simulate."""
    func = click.option(
        "--workers",
        "-w",
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


@cli.command(name="model-check")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@_common_tlc_options
@click.option(
    "--save-states",
    "-s",
    is_flag=True,
    help="Export the reachable state space as a Graphviz .dot file.",
)
@click.option(
    "--export-json",
    "-j",
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

    model_path = model_path if model_path else module_path.with_suffix(".cfg")
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
        from .tools.llm import explain_tlc_error
        explain_tlc_error(
            run.log_file.read_text(),
            CONSOLE,
            backend_name=llm_backend,
            tlc_run=run,
        )


@cli.command(name="simulate")
@click.argument(
    "module_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@_common_tlc_options
@click.option(
    "--depth",
    "-d",
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

    model_path = model_path if model_path else module_path.with_suffix(".cfg")
    run = tlc.simulate(
        module_path,
        model_path,
        workers=workers,
        max_heap_size=max_heap_size,
        community_modules=community_modules,
        external_modules=list(external_module),
        depth=depth,
        seed=seed,
    )

    if explain and not run.success and run.log_file and run.log_file.exists():
        from .tools.llm import explain_tlc_error
        explain_tlc_error(
            run.log_file.read_text(),
            CONSOLE,
            backend_name=llm_backend,
            tlc_run=run,
        )


@cli.command(name="parse")
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


@cli.command(name="proof-check")
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
    timeout: Optional[int],
) -> None:
    """
    Check TLA+ proofs with TLAPS (tlapm).

    Runs tlapm in toolbox mode on the given proof file and displays
    per-obligation proving progress.  Exits with a non-zero status when
    any obligation fails to be proved.
    """
    from datetime import timedelta

    if not tlapm.is_available():
        raise click.ClickException(
            "tlapm is not installed.  Install it and re-run."
        )

    timeout_td = timedelta(seconds=timeout) if timeout is not None else None
    run = tlapm.prove(
        module_path,
        stretch=stretch,
        community_modules=community_modules,
        timeout=timeout_td,
    )

    if not run.success:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
