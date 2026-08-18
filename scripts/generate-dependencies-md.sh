#!/usr/bin/env bash
# Generates python/DEPENDENCIES.md from the nix devShell environment.
# Run from repo root: nix develop --command ./scripts/generate-dependencies-md.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="$REPO_ROOT/python/DEPENDENCIES.md"

python3 << 'PYEOF' > "$OUTPUT"
import importlib.metadata
from datetime import date

pkgs = sorted(
    ((d.name, d.version) for d in importlib.metadata.distributions()),
    key=lambda x: x[0].lower(),
)

# Dev-only packages (from pyproject.toml [dependency-groups].dev)
dev_only = {"pytest", "mypy", "mypy_extensions", "luma.emulator", "PyHotKey",
            "pynput", "python-xlib", "pygame", "pathspec", "pluggy", "iniconfig"}

# Build/infra packages not relevant to PiFinder
infra = {"pip", "flit_core", "virtualenv", "distlib", "filelock", "platformdirs",
         "packaging", "setuptools"}

prod = [(n, v) for n, v in pkgs if n not in dev_only and n not in infra]
dev = [(n, v) for n, v in pkgs if n in dev_only]

print(f"""\
> **Auto-generated** from the Nix development shell on {date.today()}.
> Do not edit manually — regenerate with:
> ```
> nix develop --command ./scripts/generate-dependencies-md.sh
> ```

> **Note:** These dependencies are declared in `python/pyproject.toml`, pinned in
> `python/uv.lock`, and realized into the Nix store via uv2nix. Some packages
> require system libraries or hardware (SPI, I2C, GPIO) only available on the
> Raspberry Pi.

# Python Dependencies

Python {'.'.join(str(x) for x in __import__('sys').version_info[:3])}

## Runtime

| Package | Version |
|---------|---------|""")

for name, ver in prod:
    print(f"| {name} | {ver} |")

print(f"""
## Development only

| Package | Version |
|---------|---------|""")

for name, ver in dev:
    print(f"| {name} | {ver} |")
PYEOF

echo "Generated $OUTPUT"
