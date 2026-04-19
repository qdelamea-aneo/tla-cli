"""Hatchling build hook: download and bundle TLA+ tool artifacts into the wheel.

Runs automatically during `uv build` / `hatch build`. Downloads:
  - tla2tools.jar        (platform-independent)
  - CommunityModules-deps.jar  (platform-independent)
  - tlapm binary         (platform-specific; skipped for unsupported platforms)

Required environment variables (only when the artifact is not already present):
  TLA2TOOLS_VERSION       e.g. "1.8.0"
  COMMUNITY_MODULES_VERSION  e.g. "202604061452"
  TLAPM_VERSION           e.g. "1.6.0-pre"

Optional:
  TLAPM_SKIP_BUNDLE=1     Skip TLAPM entirely; produce a universal JAR-only wheel.
  GITHUB_TOKEN            Passed as Bearer token to avoid GitHub API rate limits.

When a TLAPM binary is successfully bundled the wheel is tagged as
platform-specific (e.g. ``py3-none-linux_x86_64``). Otherwise a universal
``py3-none-any`` wheel is produced containing only the JARs.
"""

import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


# ── Wheel platform tags per (system, machine) ─────────────────────────────────
# Use the minimum macOS deployment target that matches TLAPM CI builds.
PLATFORM_TAGS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux_x86_64",
    ("Darwin", "arm64"): "macosx_13_0_arm64",
}


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            "Set it before building, e.g.:\n"
            f"  {name}=<version> uv build"
        )
    return val


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        tools_dir = Path("tla_cli/data/tools")
        tools_dir.mkdir(parents=True, exist_ok=True)

        self._download_jars(tools_dir)
        self._bundle_tlapm(tools_dir, build_data)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _github_api(self, url: str) -> dict:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return json.loads(resp.read())

    def _fetch(self, url: str, dest: Path) -> None:
        print(f"  Downloading {url}", flush=True)
        req = urllib.request.Request(url)
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MB
            with dest.open("wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        mb = downloaded // (1024 * 1024)
                        total_mb = total // (1024 * 1024)
                        print(f"\r  {mb}/{total_mb} MB ({pct}%)", end="", flush=True)
            if total:
                print(flush=True)

    def _download_jars(self, tools_dir: Path) -> None:
        tla2tools = tools_dir / "tla2tools.jar"
        if not tla2tools.exists():
            version = _require_env("TLA2TOOLS_VERSION")
            self._fetch(
                f"https://github.com/tlaplus/tlaplus/releases/download"
                f"/v{version}/tla2tools.jar",
                tla2tools,
            )

        cm_jar = tools_dir / "CommunityModules-deps.jar"
        if not cm_jar.exists():
            version = _require_env("COMMUNITY_MODULES_VERSION")
            self._fetch(
                f"https://github.com/tlaplus/CommunityModules/releases/download"
                f"/{version}/CommunityModules-deps.jar",
                cm_jar,
            )

    def _find_tlapm_asset(
        self, assets: list[dict], system: str, machine: str
    ) -> dict | None:
        sys_lower = system.lower()
        mach_lower = machine.lower()
        for asset in assets:
            name = asset["name"].lower()
            if not (name.endswith(".tar.gz") or name.endswith(".zip")):
                continue
            if sys_lower == "linux" and "linux" in name and mach_lower in name:
                return asset
            if sys_lower == "darwin" and "darwin" in name and mach_lower in name:
                return asset
            if sys_lower == "windows" and ("win" in name):
                return asset
        return None

    def _bundle_tlapm(self, tools_dir: Path, build_data: dict) -> None:
        if os.environ.get("TLAPM_SKIP_BUNDLE"):
            print("  TLAPM_SKIP_BUNDLE set; skipping TLAPM — building universal wheel.")
            return

        system = platform.system()
        machine = platform.machine()
        key = (system, machine)

        tlapm_bin_dir = tools_dir / "tlapm" / "bin"
        tlapm_bin = tlapm_bin_dir / "tlapm"

        if not tlapm_bin.exists():
            tlapm_version = _require_env("TLAPM_VERSION")
            print(f"  Fetching TLAPM {tlapm_version} release info from GitHub…", flush=True)
            release = self._github_api(
                f"https://api.github.com/repos/tlaplus/tlapm/releases/tags/{tlapm_version}"
            )
            asset = self._find_tlapm_asset(release.get("assets", []), system, machine)
            if asset is None:
                print(
                    f"  No TLAPM binary for {system}/{machine} in release {tlapm_version};"
                    " building universal wheel (JARs only)."
                )
                return

            with tempfile.TemporaryDirectory() as tmpdir:
                archive = Path(tmpdir) / asset["name"]
                self._fetch(asset["browser_download_url"], archive)
                with tarfile.open(archive) as tar:
                    tar.extractall(tmpdir)

                candidates = [
                    p
                    for p in Path(tmpdir).rglob("tlapm")
                    if p.is_file() and p.stat().st_size > 0
                ]
                if not candidates:
                    print(f"  WARNING: tlapm binary not found in {asset['name']}; skipping.")
                    return

                candidates.sort(key=lambda p: (0 if "bin" in p.parts else 1, str(p)))
                tlapm_bin_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidates[0], tlapm_bin)
                tlapm_bin.chmod(
                    tlapm_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )

        tag = PLATFORM_TAGS.get(key)
        if tag:
            build_data["tag"] = f"py3-none-{tag}"
            print(f"  Bundling TLAPM; wheel tagged as {build_data['tag']}.")
        else:
            print(
                f"  TLAPM bundled but no wheel tag defined for {system}/{machine};"
                " building universal wheel."
            )
