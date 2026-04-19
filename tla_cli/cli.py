import os

import rich_click as click

from .commands import (
    tla_model_check,
    tla_simulate,
    tla_parse,
    tla_proof_check,
    tla_run,
)
from .constants import CONSOLE, LOGGER, WORKDIR, repl
from .utils import AliasedGroup, error_handler


_BANNER = r"""
 _____  _        _    _
|_   _|| |      / \ _| |_
  | |  | |     / _ \ |_|
  | |  | |___ / ___ \
  |_|  |_____/_/   \_\
"""


def _show_vibecode_warning() -> None:
    if os.environ.get("TLA_NO_VIBECODE_WARNING"):
        return
    LOGGER.warning(
        "vibecoded CLI — AI-generated, may produce incorrect results. "
        "Verify against raw tool output when in doubt. "
        "Suppress: TLA_NO_VIBECODE_WARNING=1"
    )


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
    _show_vibecode_warning()
    CONSOLE.print(_BANNER, style="bold blue", highlight=False)
    WORKDIR.mkdir(exist_ok=True)

    if ctx.invoked_subcommand is None:
        repl.start()


cli.add_command(tla_model_check)
cli.add_command(tla_simulate)
cli.add_command(tla_parse)
cli.add_command(tla_proof_check)
cli.add_command(tla_run)


if __name__ == "__main__":
    cli()
