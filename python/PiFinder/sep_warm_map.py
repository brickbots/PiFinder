#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Build the SEP warm-pixel map from stage-dump corpora.

Warm pixels are static single-pixel sensor defects that dominate SEP's
detection counts on empty sky (field bench 2026-07-28: 19 positions
accounted for 55% of all detections across a night of frames). This
tool finds them by same-channel neighbour excess recurring at a fixed
position across many frames, and writes the map ``sep_shadow`` loads at
startup.

Usage (device, any mix of directories holding raw-frame dumps)::

    python -m PiFinder.sep_warm_map ~/PiFinder_data/captures
    python -m PiFinder.sep_warm_map ~/frames --dry-run

Inputs are 16-bit raw rasters found anywhere under the given dirs, in
solver_raw orientation (profile rot90 applied):

* ``*_raw_full.png`` -- uncropped frames, used as-is.
* ``*_raw_cropped.png`` -- crop-window frames; positions are offset back
  into full-frame coordinates via the camera profile. Only valid for
  profiles without a rotation (crop happens before rot90), so cropped
  input is refused when ``rotation_90 != 0``.

The two corpora complement each other: cropped dumps exist on every
solve-failure streak, full-frame dumps cover the vignette border region
outside the crop window.

Feed DARK corpora (night / lens-cap / dim indoor). Warm pixels are only
detectable against a low background; bright twilight frames dilute the
per-group recurrence fraction and drop legitimate positions (observed
2026-07-28: adding a bright evening's dumps shrank the map 57 -> 40 and
lost census-validated defects).
"""

import argparse
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from PiFinder import utils
from PiFinder.sep_detect import build_warm_pixel_map
from PiFinder.sqm.camera_profiles import get_camera_profile

logger = logging.getLogger("Solver.SepWarmMap")

DEFAULT_OUT = utils.data_dir / "sep_warm_pixels.npy"


def _load_frames(dump_dirs):
    """Yield (kind, array) for every raw stage raster under the dirs."""
    for root in dump_dirs:
        for pattern, kind in (
            ("*_raw_full.png", "full"),
            ("*_raw_cropped.png", "cropped"),
        ):
            for path in sorted(Path(root).rglob(pattern)):
                yield kind, np.asarray(Image.open(path)).astype(np.uint16)


def build_map(
    dump_dirs,
    camera_type: str = "imx462",
    min_excess_adu: float = 45.0,
    min_recurrence: float = 0.7,
) -> np.ndarray:
    """Aggregate all dumps into one full-frame warm-pixel map."""
    profile = get_camera_profile(camera_type)
    # Group frames by kind+shape: recurrence is only meaningful within a
    # group of identically-framed captures.
    groups = defaultdict(list)
    for kind, frame in _load_frames(dump_dirs):
        if frame.ndim != 2:
            continue
        if kind == "cropped" and profile.rotation_90 != 0:
            raise SystemExit(
                f"cropped dumps can't be mapped for {camera_type} "
                "(crop precedes rot90); use raw_full dumps"
            )
        groups[(kind, frame.shape)].append(frame)

    positions = []
    for (kind, shape), frames in sorted(groups.items()):
        pts = build_warm_pixel_map(
            frames, min_excess_adu=min_excess_adu, min_recurrence=min_recurrence
        )
        if kind == "cropped":
            pts = pts + np.array([profile.crop_y[0], profile.crop_x[0]], dtype=np.int32)
        logger.info(
            "%s %s: %d frames -> %d warm pixels", kind, shape, len(frames), len(pts)
        )
        positions.append(pts)

    if not positions:
        return np.empty((0, 2), dtype=np.int32)
    merged = np.vstack(positions)
    # Dedupe positions found by both corpora (2 px grid, well inside the
    # 4 px match radius detect_stars uses).
    merged = np.unique(merged // 2, axis=0) * 2
    return merged.astype(np.int32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("dump_dirs", nargs="+", help="dirs containing stages_* dumps")
    parser.add_argument("--camera", default="imx462", help="camera profile name")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    # Defaults validated on the 2026-07-27 night corpus: a 55-position map
    # covered all 19 recurring SEP-census cells and cut empty-sky counts
    # 25.0 -> 5.5 mean, while masking only ~0.14% of the frame area.
    parser.add_argument("--min-excess-adu", type=float, default=45.0)
    parser.add_argument("--min-recurrence", type=float, default=0.7)
    parser.add_argument(
        "--dry-run", action="store_true", help="report only, write nothing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    warm = build_map(
        args.dump_dirs,
        camera_type=args.camera,
        min_excess_adu=args.min_excess_adu,
        min_recurrence=args.min_recurrence,
    )
    print(f"{len(warm)} warm pixels total")
    if args.dry_run:
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, warm)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
