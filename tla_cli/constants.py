import logging
import os

from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .packages import LocalBinaryPackage
from .tools import TLC, REPL, SANY, TLAPM


VALID = "[green]✓[/green]"
CROSS = "[red]✗[/red]"
UNCHANGED = "[yellow]~[/yellow]"

BUNDLED_TOOLS_DIR = Path(__file__).parent / "data" / "tools"
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


tla2tools = LocalBinaryPackage(
    name="TLA2Tools",
    location=BUNDLED_TOOLS_DIR / "tla2tools.jar",
    logger=LOGGER,
    console=CONSOLE,
)
community_modules = LocalBinaryPackage(
    name="CommunityModules",
    location=BUNDLED_TOOLS_DIR / "CommunityModules-deps.jar",
    logger=LOGGER,
    console=CONSOLE,
)

repl = REPL(main_class="tlc2.REPL", pkg=tla2tools, logger=LOGGER, console=CONSOLE)

tlc = TLC(
    main_class="tlc2.TLC",
    data_path=RUN_DATA_DIR,
    community_modules=community_modules,
    pkg=tla2tools,
    logger=LOGGER,
    console=CONSOLE,
)

sany = SANY(
    community_modules=community_modules,
    pkg=tla2tools,
    logger=LOGGER,
    console=CONSOLE,
    data_path=RUN_DATA_DIR,
)

_tlapm_binary = BUNDLED_TOOLS_DIR / "tlapm" / "bin" / (
    "tlapm.exe" if os.name == "nt" else "tlapm"
)
_tlapm_pkg = LocalBinaryPackage(
    name="tlapm",
    location=_tlapm_binary,
    logger=LOGGER,
    console=CONSOLE,
)
tlapm = TLAPM(
    pkg=_tlapm_pkg,
    community_modules_dir=BUNDLED_TOOLS_DIR / "CommunityModules-deps",
    logger=LOGGER,
    console=CONSOLE,
    data_path=RUN_DATA_DIR,
)
