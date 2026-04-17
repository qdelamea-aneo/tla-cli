# tla-cli

A command-line tool that simplifies working with [TLA+](https://lamport.azurewebsites.net/tla/tla.html) — the formal specification language by Leslie Lamport. It wraps TLC (model checker), SANY (parser), and TLAPS (proof system) behind a single `tla` command with rich terminal output, package management, and manifest-driven batch processing.

---

> **⚠ Vibe-coded project**
>
> This CLI was generated mostly by AI (Claude) with minimal manual review. It may contain bugs, produce incorrect output, or behave unexpectedly in edge cases. **Always verify results against the raw TLC / SANY / tlapm output before drawing conclusions.** Use with appropriate scepticism.
>
> Set `TLA_NO_VIBECODE_WARNING=1` to suppress the in-CLI warning banner.

---

## Features

- **Model checking** — exhaustive BFS and random simulation via TLC
- **Parsing & semantic analysis** — SANY module validation
- **Proof checking** — TLAPS obligation tracking with per-proof progress
- **Package management** — install, upgrade, and uninstall TLA+ tool JARs from GitHub releases
- **Manifest-driven runs** — declare all your specs in a single YAML file and run them in batch
- **LLM-powered explanations** — on failure, stream a human-readable explanation from Claude, OpenAI, Gemini, or Mistral
- **JSON output** — machine-readable results for CI/CD pipelines
- **Rich terminal UI** — progress bars, tables, and colour output (disable with `--no-progress`)

## Requirements

- Python ≥ 3.10
- Java runtime (for TLC and SANY)
- [tlapm](https://tla.msr-inria.inria.fr/tlaps/content/Home.html) on `$PATH` (only needed for `proof-check`)

## Installation

```bash
pip install tla-cli
```

Or from source:

```bash
git clone https://github.com/qdelamea/tla-cli
cd tla-cli
pip install -e .
```

Install with LLM explanation support:

```bash
pip install "tla-cli[llm]"
```

## Quick start

### Install the TLA+ tools

```bash
tla package install          # installs tla2tools and community-modules
tla package list             # show installed versions
```

### Parse a spec

```bash
tla parse MySpec.tla
# alias: tla p MySpec.tla
```

### Model check

```bash
tla model-check MySpec.tla --config MySpec.cfg
# alias: tla mc MySpec.tla --config MySpec.cfg

# Use all CPU cores and 4 GB heap
tla mc MySpec.tla --config MySpec.cfg --workers auto --max-heap-size 4G

# Random simulation (faster, non-exhaustive)
tla simulate MySpec.tla --config MySpec.cfg --num-traces 1000
# alias: tla sim ...
```

### Check proofs

```bash
tla proof-check MyProofs.tla
# alias: tla pc MyProofs.tla
```

### LLM explanation on failure

```bash
tla mc MySpec.tla --config MySpec.cfg --explain
tla mc MySpec.tla --config MySpec.cfg --explain --llm-backend openai
```

### Machine-readable output

```bash
tla mc MySpec.tla --config MySpec.cfg --format json
```

## Commands

| Command | Alias | Description |
|---|---|---|
| `model-check` | `mc` | Exhaustive BFS model checking with TLC |
| `simulate` | `sim` | Random trace simulation with TLC |
| `parse` | `p` | Parse and semantic-check with SANY |
| `proof-check` | `pc` | Verify TLA+ proofs with TLAPS |
| `package` | — | Manage TLA+ tool installations |
| `run` | — | Batch run from a manifest YAML |

Run `tla <command> --help` for full option details.

## Manifest-driven batch runs

For projects with multiple specs and models, define everything in a `manifest.yaml`:

```yaml
modules:
  - path: specs/MySpec.tla
    dependencies:
      community_modules: true
    models:
      - name: small
        path: specs/MySpec.cfg
        timeout: "0:05:00"
        mode: exhaustive          # or "simulation"
        settings:
          workers: auto
          max_heap_size: 4G
        checks:
          success: true
          total_states: 1234
          distinct_states: 567
    proofs:
      - name: all
        path: specs/MyProofs.tla
        timeout: "0:10:00"
        settings:
          stretch: 2              # multiply backend timeouts
        checks:
          success: true
          num_obligations: 42
```

Then run:

```bash
tla run manifest.yaml

# Run only a specific module or action
tla run manifest.yaml --filter MySpec
tla run manifest.yaml --filter MySpec/small

# Skip actions that passed last time
tla run manifest.yaml --skip-passed

# CI-friendly JSON output
tla run manifest.yaml --format json
```

## Package management

```bash
tla package list
tla package install tla2tools
tla package install community-modules
tla package install tla2tools==1.5.7    # pin a version
tla package upgrade tla2tools
tla package uninstall tla2tools
```

## Environment variables

All options can also be set via environment variables using the `TLA_` prefix (e.g. `TLA_WORKERS=auto`).

| Variable | Effect |
|---|---|
| `TLA_NO_VIBECODE_WARNING=1` | Suppress the AI-generated warning banner |

## Development

```bash
# Install dev dependencies
pip install -e ".[llm]"
pip install pytest ruff mypy

# Run tests
pytest tests/

# Lint
ruff check cli/ tests/

# Type check
mypy cli/
```

## License

[MIT](LICENSE)
