# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest tests/ -v
uv run pytest tests/ -m integration   # integration tests only (require real TLA+ tools)
uv run pytest tests/test_foo.py::test_bar  # single test

# Lint & format
uv run ruff check .
uv run ruff format --check .
uv run ruff format .

# Type checking
uv run mypy tla_cli/

# Build wheel (requires env vars: TLA2TOOLS_VERSION, COMMUNITY_MODULES_VERSION, TLAPM_VERSION)
uv build
```

## Architecture

**Three-layer design:**

1. **CLI layer** (`tla_cli/commands/`) — Click command handlers that validate arguments, invoke wrappers, and render output via Rich.
2. **Wrapper layer** (`tla_cli/wrappers/`) — Abstractions over TLA+ tools. `JavaClassTool` (in `java.py`) is the base for JVM-based tools (TLC, SANY, REPL); `TLAPM` inherits from the base `Tool`.
3. **Manifest layer** (`tla_cli/manifest/`) — YAML-driven batch orchestration. `Manifest` in `processor.py` loads and validates YAML (Pydantic schema in `models.py`), then iterates modules and invokes wrappers sequentially.

**Key data flow for `tla model-check`:**
1. `commands/check.py` parses args → creates an `AppContext` from `cli.py`
2. `TLC.model_check()` builds the Java classpath (tla2tools.jar + community modules), spawns the subprocess, and streams output through `TLCOutputParser` (`wrappers/tlc_output.py`, ~1200 LOC) in real time
3. Output is parsed and rendered with Rich progress/panels; results returned as `TLCRun` dataclass
4. Command handler serializes to JSON or Rich display; exit code reflects success/failure

**`AppContext`** (defined in `cli.py`) is the Click `ctx.obj` shared across all commands:
```python
@dataclass
class AppContext:
    tlc: TLC
    sany: SANY
    tlapm: TLAPM
    repl: REPL
    cache_dir: Path   # .tlacache/ by default
```

**Bundled tools** live in `tla_cli/tools/` and are downloaded at build time by `hatch_build.py`:
- `tla2tools.jar` — TLC model checker + SANY parser
- `CommunityModules-deps.jar` — standard TLA+ library extensions
- `tlapm` binary — proof checker (Linux x86_64 or macOS ARM64)

Use `TLAPM_SKIP_BUNDLE=1` to produce a JAR-only universal wheel without the `tlapm` binary.

## Project Conventions

- Line length: 140 characters (configured in `pyproject.toml` under `[tool.ruff]`)
- Ruff selects `E`, `F`, `I` rules; type annotations required (mypy strict-ish)
- Tests marked `@pytest.mark.integration` hit real TLC/SANY/TLAPS and are slow; unmarked tests are unit tests
- Coverage source is `tla_cli/` (excludes bundled JARs/binaries)
