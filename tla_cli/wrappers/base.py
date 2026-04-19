from abc import ABC
from logging import Logger

from rich.console import Console


class Tool(ABC):
    def __init__(self, name: str, logger: Logger, console: Console) -> None:
        self.name = name
        self.logger = logger
        self.console = console
