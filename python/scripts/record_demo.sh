#!/usr/bin/env bash
# Start PiFinder on this computer with the demo display: the UI inside a
# photo of the device, with a glow on each pressed button. Optionally
# record the window to an MP4 file. Run with -h for the options.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: python/scripts/record_demo.sh [options]

With no options, the demo display opens and nothing is recorded.

  --record FILE          Record the window to FILE (MP4, 30 fps).
  --record-audio         With --record, also record the default microphone.
  --script NAME          Press the keys in scripts/NAME.pfs, for example demo_tour.
  --display pg_demo_176  Use the 176x176 rev4 screen layout.
  -h, --help             Show this text.

Other PiFinder.main options pass through. Stop with Ctrl+C or close the
window. The MP4 file is complete when the prompt comes back.

Keys: arrows, 0-9, + and -, Enter, Space or Z for SQUARE, M for a long SQUARE,
Ctrl + key for a SQUARE chord. Click a button in the photo to press it.
Right click is a long press. Ctrl + click is a SQUARE chord.
EOF
}

# The script runs PiFinder from python/. Make a relative --record path
# relative to the folder you started the script in.
args=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --record)
            [ $# -ge 2 ] || { echo "--record needs a file name" >&2; exit 2; }
            args+=("--record" "$(realpath -m -- "$2")")
            shift 2
            ;;
        --record=*)
            args+=("--record" "$(realpath -m -- "${1#--record=}")")
            shift
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

usage
echo
cd "$(dirname "$0")/.."
# The Nix dev shell has its own Python environment. Outside it, use uv.
if [ -n "${IN_NIX_SHELL:-}" ]; then
    python=(python)
else
    python=(uv run python)
fi
exec "${python[@]}" -m PiFinder.main -fh --camera debug --keyboard local \
    --display pg_demo "${args[@]}"
