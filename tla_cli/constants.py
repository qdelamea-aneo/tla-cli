import logging
import os

from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .wrappers import TLC, REPL, SANY, TLAPM


VALID = "[green]✓[/green]"
CROSS = "[red]✗[/red]"
UNCHANGED = "[yellow]~[/yellow]"

TOOLS_DIR = Path(__file__).parent / "tools"
TLA2TOOLS_JAR = TOOLS_DIR / "tla2tools.jar"
COMMUNITY_MODULES_JAR = TOOLS_DIR / "CommunityModules-deps.jar"
TLAPM_BINARY = TOOLS_DIR / "tlapm" / "bin" / ("tlapm.exe" if os.name == "nt" else "tlapm")

WORKDIR = Path.cwd() / ".tla"
RUN_DATA_DIR = WORKDIR / "data"

CONSOLE = Console()

logging.basicConfig(
    level="WARNING",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=CONSOLE)],
)
LOGGER = logging.getLogger("rich")

repl = REPL(main_class="tlc2.REPL", tla2tools_jar=TLA2TOOLS_JAR, logger=LOGGER, console=CONSOLE)

tlc = TLC(
    main_class="tlc2.TLC",
    data_path=RUN_DATA_DIR,
    tla2tools_jar=TLA2TOOLS_JAR,
    community_modules_jar=COMMUNITY_MODULES_JAR,
    logger=LOGGER,
    console=CONSOLE,
)

sany = SANY(
    tla2tools_jar=TLA2TOOLS_JAR,
    community_modules_jar=COMMUNITY_MODULES_JAR,
    logger=LOGGER,
    console=CONSOLE,
    data_path=RUN_DATA_DIR,
)

tlapm = TLAPM(
    binary_path=TLAPM_BINARY,
    community_modules_dir=TOOLS_DIR / "CommunityModules-deps",
    logger=LOGGER,
    console=CONSOLE,
    data_path=RUN_DATA_DIR,
)
