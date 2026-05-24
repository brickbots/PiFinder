#!/usr/bin/env python3
"""Convert a raw PiFinder screenshot into a documentation-ready image.

PiFinder screens are 128x128 and rendered in the red channel only (the OLED is
driven red-only to preserve night vision), so a raw capture looks small and dim
dark-red on black. The published docs use larger, brighter images: the red
intensity is recolored onto a warm amber tint and the image is scaled up. The
amber recolor is what produces the "brighter" look — amber is far more luminous
than dark red at the same intensity — so no separate brightness curve is needed.

Pipeline (matched to the existing docs/source/images screenshots):
  1. intensity = the brightest channel per pixel (== the red channel for a
     red-only capture; also works for grayscale input)
  2. recolor: out = tint * (intensity / 255)   [linear ramp, black stays black]
  3. upscale by --scale (default 2x -> 128 becomes the 256x256 docs use)

Defaults (the house values measured from the existing doc images):
  tint = 245,76,10   scale = 2   resample = nearest (crisp doubled pixels)

Naming is explicit: you pass the output path (-o) or an output directory
(--out-dir) so each doc image can be named to fit its place in the manual.

Examples:
  # one screenshot, named for its doc context:
  python screenshot_to_doc.py /tmp/pf_status.png \\
      -o docs/source/images/user_guide/status_screen_docs.png

  # batch into a page's image folder, keeping each input's basename:
  python screenshot_to_doc.py /tmp/shot1.png /tmp/shot2.png \\
      --out-dir docs/source/images/quick_start/

  # smoother upscale instead of crisp pixels:
  python screenshot_to_doc.py raw.png -o out.png --resample lanczos

Requires Pillow (already a PiFinder dependency).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageOps
except ImportError:
    sys.exit(
        "Pillow is required. Install it with: pip install Pillow\n"
        "(Pillow is already a PiFinder dependency, so activating the project "
        "venv is usually enough.)"
    )

RESAMPLE = {
    "nearest": Image.NEAREST,
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
}


def parse_tint(text: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(p) for p in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"tint must be R,G,B integers, got {text!r}")
    if len(parts) != 3 or any(not 0 <= p <= 255 for p in parts):
        raise argparse.ArgumentTypeError(f"tint must be three 0-255 values, got {text!r}")
    return parts  # type: ignore[return-value]


def convert(src: Path, dst: Path, tint, scale: int, resample) -> None:
    """Recolor a raw screenshot onto the tint and scale it up."""
    im = Image.open(src).convert("RGB")
    r, g, b = im.split()
    # Per-pixel brightest channel == intensity. For a red-only PiFinder capture
    # this is just the red channel; for grayscale it's the gray value.
    intensity = ImageChops.lighter(ImageChops.lighter(r, g), b)
    # Linear ramp black->tint: value v maps to tint * (v/255).
    colored = ImageOps.colorize(intensity, black=(0, 0, 0), white=tint)
    w, h = colored.size
    colored = colored.resize((w * scale, h * scale), resample)
    dst.parent.mkdir(parents=True, exist_ok=True)
    colored.save(dst)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert raw PiFinder screenshots into documentation-ready images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("inputs", nargs="+", type=Path, help="raw screenshot(s) to convert")
    p.add_argument("-o", "--output", type=Path, help="output path (single input only)")
    p.add_argument("--out-dir", type=Path, help="output directory (keeps each input's name)")
    p.add_argument("--scale", type=int, default=2, help="upscale factor (default: 2)")
    p.add_argument("--tint", type=parse_tint, default="245,76,10",
                   help="amber tint as R,G,B (default: 245,76,10)")
    p.add_argument("--resample", choices=RESAMPLE, default="nearest",
                   help="upscale method (default: nearest = crisp doubled pixels)")
    p.add_argument("-f", "--force", action="store_true", help="overwrite existing files")
    args = p.parse_args(argv)

    tint = args.tint if isinstance(args.tint, tuple) else parse_tint(args.tint)
    resample = RESAMPLE[args.resample]

    inputs = [Path(i) for i in args.inputs]
    missing = [i for i in inputs if not i.is_file()]
    if missing:
        p.error("input file(s) not found: " + ", ".join(str(m) for m in missing))

    # Resolve output paths.
    if args.output and args.out_dir:
        p.error("use either -o/--output or --out-dir, not both")
    if len(inputs) > 1 and args.output:
        p.error("-o/--output works with a single input; use --out-dir for multiple")
    if not args.output and not args.out_dir:
        p.error("specify an output: -o <file.png> for one input, or --out-dir <dir>")

    jobs = []
    for src in inputs:
        dst = args.output if args.output else (args.out_dir / src.name)
        jobs.append((src, dst))

    if not args.force:
        clashes = [str(dst) for _, dst in jobs if dst.exists()]
        if clashes:
            p.error("output exists (use --force to overwrite): " + ", ".join(clashes))

    for src, dst in jobs:
        convert(src, dst, tint, args.scale, resample)
        print(f"{src}  ->  {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
