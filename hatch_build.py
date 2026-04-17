"""Hatchling build hook: download and bundle TLA+ tool artifacts into the wheel.

Runs automatically during `uv build` / `hatch build`. Downloads:
  - tla2tools.jar        (platform-independent)
  - CommunityModules-deps.jar  (platform-independent)
  - tlapm binary         (platform-specific; skipped for unsupported platforms)

When a TLAPM binary is successfully bundled the wheel is tagged as
platform-specific (e.g. ``py3-none-linux_x86_64``). Otherwise a universal
``py3-none-any`` wheel is produced containing only the JARs.
"""

import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


# ── Pinned tool versions ──────────────────────────────────────────────────────

TLA2TOOLS_VERSION = "1.8.0"
COMMUNITY_MODULES_VERSION = "202604061452"
TLAPM_VERSION = "1.6.0-pre"

# ── TLAPM release asset names per (system, machine) ──────────────────────────

TLAPM_ASSETS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): f"tlapm-{TLAPM_VERSION}-x86_64-linux-gnu.tar.gz",
    ("Darwin", "arm64"): f"tlapm-{TLAPM_VERSION}-arm64-darwin.tar.gz",
}

# ── Wheel platform tags per (system, machine) ─────────────────────────────────
# Use the minimum macOS deployment target that matches TLAPM CI builds.
PLATFORM_TAGS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux_x86_64",
    ("Darwin", "arm64"): "macosx_13_0_arm64",
}


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        tools_dir = Path("tla_cli/data/tools")
        tools_dir.mkdir(parents=True, exist_ok=True)

        self._download_jars(tools_dir)
        self._bundle_tlapm(tools_dir, build_data)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fetch(self, url: str, dest: Path) -> None:
        print(f"  Downloading {url}")
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            dest.write_bytes(resp.read())

    def _download_jars(self, tools_dir: Path) -> None:
        tla2tools = tools_dir / "tla2tools.jar"
        if not tla2tools.exists():
            self._fetch(
                f"https://github.com/tlaplus/tlaplus/releases/download"
                f"/v{TLA2TOOLS_VERSION}/tla2tools.jar",
                tla2tools,
            )

        cm_jar = tools_dir / "CommunityModules-deps.jar"
        if not cm_jar.exists():
            self._fetch(
                f"https://github.com/tlaplus/CommunityModules/releases/download"
                f"/{COMMUNITY_MODULES_VERSION}/CommunityModules-deps.jar",
                cm_jar,
            )

    def _bundle_tlapm(self, tools_dir: Path, build_data: dict) -> None:
        if os.environ.get("TLAPM_SKIP_BUNDLE"):
            print("  TLAPM_SKIP_BUNDLE set; skipping TLAPM — building universal wheel.")
            return

        system = platform.system()
        machine = platform.machine()
        key = (system, machine)

        asset_name = TLAPM_ASSETS.get(key)
        if asset_name is None:
            print(
                f"  No TLAPM binary available for {system}/{machine};"
                " building universal wheel (JARs only)."
            )
            return

        tlapm_bin_dir = tools_dir / "tlapm" / "bin"
        tlapm_bin = tlapm_bin_dir / "tlapm"

        if not tlapm_bin.exists():
            url = (
                f"https://github.com/tlaplus/tlapm/releases/download"
                f"/{TLAPM_VERSION}/{asset_name}"
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                archive = Path(tmpdir) / asset_name
                self._fetch(url, archive)
                with tarfile.open(archive) as tar:
                    tar.extractall(tmpdir)

                # Locate the tlapm executable inside the extracted tree.
                candidates = [
                    p
                    for p in Path(tmpdir).rglob("tlapm")
                    if p.is_file() and p.stat().st_size > 0
                ]
                if not candidates:
                    print(f"  WARNING: tlapm binary not found in {asset_name}; skipping.")
                    return

                # Prefer a file inside a bin/ directory.
                candidates.sort(key=lambda p: (0 if "bin" in p.parts else 1, str(p)))
                tlapm_bin_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidates[0], tlapm_bin)
                tlapm_bin.chmod(tlapm_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        tag = PLATFORM_TAGS.get(key)
        if tag:
            build_data["tag"] = f"py3-none-{tag}"
            print(f"  Bundling TLAPM; wheel tagged as {build_data['tag']}.")
