import os

import rich_click as click

from rich.panel import Panel
from rich.text import Text

from .commands import tla_package, tla_model_check, tla_simulate, tla_parse, tla_proof_check, tla_run
from .constants import CONSOLE, WORKDIR, TOOLS_DIR, repl
from .utils import AliasedGroup, error_handler


def _show_vibecode_warning() -> None:
    """Print a warning panel before starting the REPL.

    Suppressed when ``TLA_NO_VIBECODE_WARNING`` is set to any non-empty value.
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
@click.pass_context
@error_handler
def cli(ctx: click.Context) -> None:
    """
    Command-line tool to simplify working with TLA+.
    """
    WORKDIR.mkdir(exist_ok=True)
    TOOLS_DIR.mkdir(exist_ok=True)

    if ctx.invoked_subcommand is None:
        if repl.is_available():
            _show_vibecode_warning()
            repl.start()
        else:
            click.echo(ctx.get_help())


cli.add_command(tla_package)
cli.add_command(tla_model_check)
cli.add_command(tla_simulate)
cli.add_command(tla_parse)
cli.add_command(tla_proof_check)
cli.add_command(tla_run)


if __name__ == "__main__":
    cli()
