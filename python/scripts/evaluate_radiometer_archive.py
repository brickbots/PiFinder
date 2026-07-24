#!/usr/bin/env python3
"""Replay the shipped solve-independent radiometer over archived raw sweeps."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.radiometer import collect_radiometer_sample, radiometric_sqm


def _sweep_index(root: Path) -> dict[str, Path]:
    return {path.name: path for path in root.glob("*/sweep_*") if path.is_dir()}


def _reference(row: dict, sweep: Path):
    if row.get("ref_sqm"):
        return float(row["ref_sqm"])
    metadata = sweep / "sweep_metadata.json"
    if metadata.exists():
        value = json.loads(metadata.read_text()).get("reference_sqm")
        if value is not None:
            return float(value)
    # The oldest imx296 archive predates sweep metadata; its observing notes
    # record the hand-held SQM-L range as 17.8--17.9.
    if sweep.name == "sweep_20251031_195434":
        return 17.85
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("sweeps", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--quality",
        type=Path,
        help="Sweep-quality manifest (defaults to <sweeps>/sqm_archive_quality.json)",
    )
    args = parser.parse_args()

    sweeps = _sweep_index(args.sweeps)
    quality_path = args.quality or args.sweeps / "sqm_archive_quality.json"
    quality = json.loads(quality_path.read_text())
    sweep_keys = {
        path.name: f"{path.parent.name}/{path.name}" for path in sweeps.values()
    }
    results = defaultdict(list)
    fitted_zero_points = defaultdict(list)
    missing = []
    sequence = 0

    for row in csv.DictReader(args.csv.open()):
        sweep = sweeps.get(row["sweep"])
        reference = _reference(row, sweep) if sweep else None
        if sweep is None or reference is None:
            continue
        candidates = sorted(sweep.glob(f"{row['frame']}_*raw*.tif*"))
        if not candidates:
            # Older imx296 archive names use ``_imx296_mono.tiff``.
            candidates = sorted(sweep.glob(f"{row['frame']}_*.tif*"))
        if not candidates:
            missing.append(f"{row['sweep']}/{row['frame']}")
            continue

        sequence += 1
        profile = get_camera_profile(row["profile"])
        raw = np.asarray(Image.open(candidates[0]))
        exposure_sec = float(row["exp_ms"]) / 1000.0
        sample = collect_radiometer_sample(
            raw,
            profile,
            exposure_sec,
            sequence=sequence,
            captured_at=float(sequence),
        )
        value, details = radiometric_sqm(sample, profile)
        if value is None:
            continue
        error = value - reference
        results[(row["profile"], row["sweep"])].append(error)

        signal = details["background_corrected"]
        density = signal / details["arcsec_squared_per_pixel"]
        quality_key = sweep_keys.get(row["sweep"])
        annotation = quality.get(quality_key, {})
        if annotation.get("use_for_factory_fit", False):
            fitted_zero_points[row["profile"]].append(
                reference - 2.5 * math.log10(exposure_sec) + 2.5 * math.log10(density)
            )

    sweep_rows = []
    for (profile, sweep), errors in sorted(results.items()):
        quality_key = sweep_keys.get(sweep)
        annotation = quality.get(quality_key, {})
        sweep_rows.append(
            {
                "profile": profile,
                "sweep": sweep,
                "frames": len(errors),
                "median_error": statistics.median(errors),
                "frame_scatter": statistics.pstdev(errors) if len(errors) > 1 else 0.0,
                "condition": annotation.get("condition", "unreviewed"),
                "use_for_factory_fit": annotation.get("use_for_factory_fit", False),
                "quality_note": annotation.get("note", ""),
            }
        )
    output = {
        "sweeps": sweep_rows,
        "fitted_radiometric_zero_points": {
            profile: {
                "frames": len(values),
                "median": statistics.median(values),
                "scatter": statistics.pstdev(values),
            }
            for profile, values in fitted_zero_points.items()
        },
        "missing": missing,
    }
    rendered = json.dumps(output, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
