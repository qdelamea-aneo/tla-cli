"""Package management commands (list, install, upgrade, uninstall)."""

import re

import rich_click as click

from packaging.version import parse as parse_version
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table

from ..constants import CONSOLE, VALID, CROSS, UNCHANGED, tla2tools, community_modules
from ..utils import error_handler


# All manageable packages keyed by name.
_pkg_map = {p.name: p for p in [tla2tools, community_modules]}


@click.group(name="package")
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

    for pkg in _pkg_map.values():
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
@click.argument("pkg_specs", metavar="PACKAGE_SPEC", nargs=-1, type=str)
@error_handler
def tla_package_install(pkg_specs: tuple[str, ...]) -> None:
    """
    Install one or more TLA+ tool packages and their dependencies.

    PACKAGE_SPEC format: name or name==version (e.g. tla2tools==1.5.7)

    When no PACKAGE_SPEC is given, all known packages are installed.
    """
    if not pkg_specs:
        pkg_specs = tuple(_pkg_map.keys())

    spec_pattern = r"^([a-zA-Z0-9_-]+)(?:==([vV]?\d+\.\d+\.\d+))?$"
    pkgs_to_install = []

    for spec in pkg_specs:
        match = re.match(spec_pattern, spec)
        if not match:
            raise click.BadArgumentUsage(f"Invalid package specifier format: '{spec}'.")

        pkg_name, version_str = match.groups()
        pkg = _pkg_map.get(pkg_name)
        if pkg is None:
            raise click.BadArgumentUsage(f"Unknown package: '{pkg_name}'")

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
@click.argument("pkg_names", metavar="PACKAGE_NAME", nargs=-1, type=str)
@error_handler
def tla_package_upgrade(pkg_names: tuple[str, ...]) -> None:
    """
    Upgrade specified TLA+ tool packages to their latest versions.

    When no PACKAGE_NAME is given, all installed packages are upgraded.
    """
    if not pkg_names:
        pkg_names = tuple(_pkg_map.keys())

    pkgs_to_upgrade = []
    for pkg_name in pkg_names:
        pkg = _pkg_map.get(pkg_name)
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
@click.argument("pkg_names", metavar="PACKAGE_NAME", nargs=-1, type=str)
@error_handler
def tla_package_uninstall(pkg_names: tuple[str, ...]) -> None:
    """
    Uninstall one or more installed TLA+ tool packages.

    When no PACKAGE_NAME is given, all installed packages are uninstalled.
    """
    if not pkg_names:
        pkg_names = tuple(_pkg_map.keys())

    pkgs_to_uninstall = []
    for pkg_name in pkg_names:
        pkg = _pkg_map.get(pkg_name)
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
