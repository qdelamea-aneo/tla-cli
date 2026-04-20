import logging
from functools import partial, wraps
from typing import Any, Callable, Optional

import rich_click as click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich_click import ClickException

CONSOLE = Console()

logging.basicConfig(
    level="WARNING",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=CONSOLE)],
)
LOGGER = logging.getLogger("rich")


class BaseCliError(ClickException):
    """Base exception for CLI errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)

    def show(self, file=None):
        CONSOLE.print(Panel(self.format_message(), title="Error", style="red"))


class InternalCliError(BaseCliError):
    """Error raised when an unknown internal error occurred."""

    exit_code = 3


class ToolRuntimeError(BaseCliError):
    """Error raised when a TLA+ tool returns an error at runtime."""

    exit_code = 4


def error_handler(func: Optional[Callable[..., Any]] = None) -> Callable[..., Any]:
    """Decorator to handle errors for Click commands and ensure proper error display."""
    if func is None:
        return partial(error_handler)

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ToolRuntimeError, click.ClickException):
            raise
        except Exception as e:
            CONSOLE.print_exception()
            raise BaseCliError(f"CLI errored with exception:\n{e}") from e

    return wrapper


class AliasedGroup(click.RichGroup):
    """A Click Group subclass that supports command aliases."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        aliases = {
            "mc": "model-check",
            "sim": "simulate",
            "p": "parse",
            "pc": "proof-check",
        }
        if cmd_name in aliases:
            return click.Group.get_command(self, ctx, aliases[cmd_name])
        return None

    def resolve_command(self, ctx: click.Context, args: list[str]) -> tuple[str | None, click.Command | None, list[str]]:
        _, cmd, args = super().resolve_command(ctx, args)
        return cmd.name if cmd is not None else None, cmd, args
