import subprocess
import sys

from logging import Logger
from pathlib import Path

from rich.console import Console

from .java import JavaClassTool


class REPL(JavaClassTool):
    """TLA+ REPL tool for interactive constant expressions evaluation."""

    def __init__(
        self,
        main_class: str,
        tla2tools_jar: Path,
        logger: Logger,
        console: Console,
    ) -> None:
        super().__init__(
            name="REPL",
            classpath=tla2tools_jar,
            main_class=main_class,
            logger=logger,
            console=console,
        )

    def start(self) -> None:
        """Starts the TLA+ REPL."""
        try:
            process = subprocess.Popen(
                self.get_java_command(),
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            process.wait()
            if process.returncode != 0:
                raise RuntimeError(
                    process.stderr.read() if process.stderr else "REPL failed."
                )
        except KeyboardInterrupt:
            pass
