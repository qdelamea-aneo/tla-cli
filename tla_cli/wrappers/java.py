from logging import Logger
from pathlib import Path
from typing import Optional

from rich.console import Console

from .base import Tool


class JavaClassTool(Tool):
    """Base class for tools that wrap Java command-line applications.

    Attributes:
        name: Name of the tool.
        classpath: Base list of paths included in every Java classpath.
        main_class: Fully qualified name of the main class to run.
        max_heap_size: Default maximum heap size for the JVM (e.g., ``"4G"``).
        parallel_gc: Whether to enable parallel garbage collection by default.
    """

    def __init__(
        self,
        name: str,
        classpath: Path,
        main_class: str,
        logger: Logger,
        console: Console,
    ) -> None:
        super().__init__(name, logger, console)
        self.classpath = [classpath]
        self.main_class = main_class
        self.max_heap_size = "4G"
        self.parallel_gc = False

    def get_java_command(
        self,
        program_args: Optional[list[str]] = None,
        extra_classpath: Optional[list[Path]] = None,
        max_heap_size: Optional[str] = None,
        parallel_gc: Optional[bool] = None,
    ) -> list[str]:
        """Construct the Java command to run the tool.

        The base :attr:`classpath` is always included.  Pass *extra_classpath*
        to append entries for a single invocation without mutating shared state.
        The *max_heap_size* and *parallel_gc* parameters likewise override the
        instance defaults for that call only.

        Args:
            program_args: Arguments forwarded to the main class.
            extra_classpath: Additional classpath entries appended to the base
                :attr:`classpath` for this invocation only.
            max_heap_size: JVM ``-Xmx`` value (e.g. ``"4G"``).  Defaults to
                :attr:`max_heap_size` when not provided.
            parallel_gc: Whether to pass ``-XX:+UseParallelGC``.  Defaults to
                :attr:`parallel_gc` when not provided.

        Returns:
            List of command-line arguments suitable for :func:`subprocess.Popen`.
        """
        full_classpath = self.classpath + (extra_classpath or [])
        heap = max_heap_size if max_heap_size is not None else self.max_heap_size
        use_gc = parallel_gc if parallel_gc is not None else self.parallel_gc

        cmd = [
            "java",
            "-cp",
            ":".join(str(p) for p in full_classpath),
            f"-Xmx{heap}",
        ]
        if use_gc:
            cmd.append("-XX:+UseParallelGC")
        cmd.append(self.main_class)
        if program_args:
            cmd.extend(program_args)
        return cmd
