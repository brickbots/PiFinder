#!/usr/bin/env bash
# Push a flake dev shell, with every package in it, to the PiFinder cache.
#
# Usage: push_dev_shell.sh <system> [shell]
#
# The mkShell output is one small text file that references no packages, so a
# push of that output leaves the packages out of the cache. The shell's
# inputDerivation references every package the shell uses, so this script
# pushes that.
set -euo pipefail

system="$1"
shell="${2:-default}"

path="$(nix build ".#devShells.$system.$shell.inputDerivation" --no-link --print-out-paths)"
attic push pifinder:pifinder "$path"
