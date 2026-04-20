import os

from dataclasses import dataclass
from pathlib import Path

import rich_click as click

from .commands import (
    tla_model_check,
    tla_simulate,
    tla_parse,
    tla_proof_check,
    tla_run,
)
from .utils import AliasedGroup, CONSOLE, LOGGER, error_handler
from .wrappers import TLC, REPL, SANY, TLAPM


_TOOLS_DIR = Path(__file__).parent / "tools"
_TLA2TOOLS_JAR = _TOOLS_DIR / "tla2tools.jar"
_COMMUNITY_MODULES_JAR = _TOOLS_DIR / "CommunityModules-deps.jar"
_TLAPM_BINARY = _TOOLS_DIR / "tlapm" / "bin" / ("tlapm.exe" if os.name == "nt" else "tlapm")

_BANNER = r"""
 _____  _        _    _
|_   _|| |      / \ _| |_
  | |  | |     / _ \ |_|
  | |  | |___ / ___ \
  |_|  |_____/_/   \_\
"""


@dataclass
class AppContext:
    tlc: TLC
    sany: SANY
    tlapm: TLAPM
    repl: REPL
    cache_dir: Path


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

    ctx.obj = AppContext(
        tlc=TLC(
            main_class="tlc2.TLC",
            tla2tools_jar=_TLA2TOOLS_JAR,
            community_modules_jar=_COMMUNITY_MODULES_JAR,
            logger=LOGGER,
            console=CONSOLE,
        ),
        sany=SANY(
            tla2tools_jar=_TLA2TOOLS_JAR,
            community_modules_jar=_COMMUNITY_MODULES_JAR,
            logger=LOGGER,
            console=CONSOLE,
        ),
        tlapm=TLAPM(
            binary_path=_TLAPM_BINARY,
            community_modules_dir=_TOOLS_DIR / "CommunityModules-deps",
            logger=LOGGER,
            console=CONSOLE,
        ),
        repl=REPL(
            main_class="tlc2.REPL",
            tla2tools_jar=_TLA2TOOLS_JAR,
            logger=LOGGER,
            console=CONSOLE,
        ),
        cache_dir=Path.cwd() / ".tlacache",
    )

    if ctx.invoked_subcommand is None:
        ctx.obj.repl.start()


cli.add_command(tla_model_check)
cli.add_command(tla_simulate)
cli.add_command(tla_parse)
cli.add_command(tla_proof_check)
cli.add_command(tla_run)


if __name__ == "__main__":
    cli()
