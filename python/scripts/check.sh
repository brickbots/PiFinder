#!/usr/bin/env bash
# Lint, type and test checks for the Python code. CI, the pre-commit hooks and
# developers all run this script, so every check uses the same tools: the flake
# dev shell, built from python/uv.lock by uv2nix.
#
# Usage: scripts/check.sh [lint|format|types|smoke|unit|integration|all]...
# With no stage it runs all of them. "format" reformats the code; "lint" only
# reports format faults.
set -euo pipefail

python_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_dir="$(dirname "$python_dir")"

if [ -z "${PIFINDER_DEV_SHELL:-}" ]; then
    exec nix develop "$repo_dir#default" -c "$python_dir/scripts/check.sh" "$@"
fi

cd "$python_dir"

run_stage() {
    case "$1" in
        lint)
            ruff check .
            ruff format --check .
            ;;
        format) ruff format . ;;
        types) mypy PiFinder ;;
        smoke) pytest -m smoke ;;
        unit) pytest -m unit ;;
        # The web tests need a Selenium grid and a running PiFinder.
        integration) pytest -m integration --ignore-glob='tests/test_web_*' ;;
        all)
            for stage in lint types smoke unit integration; do
                run_stage "$stage"
            done
            ;;
        *)
            echo "unknown stage: $1" >&2
            exit 2
            ;;
    esac
}

if [ "$#" -eq 0 ]; then
    set -- all
fi
for stage in "$@"; do
    echo "== $stage"
    run_stage "$stage"
done
