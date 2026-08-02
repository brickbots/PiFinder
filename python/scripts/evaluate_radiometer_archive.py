#!/usr/bin/env python3
"""Replay the shipped solve-independent radiometer over archived raw sweeps.

Two jobs, and they answer different questions:

* ``sweeps`` -- how the *currently shipped* profile constants score against
  each referenced sweep. These residuals already include the colour term on
  any sensor that carries one, so they say whether what we ship is right.
* ``radiometric_models`` -- re-derives the constant and sky-colour models from
  the archive and cross-validates them against each other, so the choice of
  model recorded in ``camera_profiles.py`` can be reproduced or refuted rather
  than taken on trust. See ADR 0026.

The model fit deliberately runs per sweep rather than per frame, and scores by
leave-one-night-out error rather than in-sample scatter; ``radiometric_fit``
explains why.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.radiometer import collect_radiometer_sample, radiometric_sqm
from PiFinder.sqm.radiometric_fit import SweepPoint, evaluate_profile


def _sweep_index(root: Path) -> dict[str, Path]:
    return {path.name: path for path in root.glob("*/sweep_*") if path.is_dir()}


def _night(sweep_name: str) -> str:
    """Group sweeps by observing night.

    Sweeps are named ``sweep_YYYYMMDD_HHMMSS``. Nights are the unit of
    independence here -- sweeps within one share sky, observer and reference
    meter -- so cross-validation holds out whole nights, never single sweeps.
    """
    match = re.search(r"(\d{8})", sweep_name)
    return match.group(1) if match else sweep_name


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
    # Per-frame values kept keyed by sweep so the model fit can reduce each
    # sweep to one point before fitting, rather than letting a long sweep
    # outvote a whole night.
    implied_by_sweep = defaultdict(list)
    ratio_by_sweep = defaultdict(list)
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
        key = (row["profile"], row["sweep"])
        # Recorded pre-clamp for every sweep, fit-eligible or not: the fit
        # needs the colour actually measured, and clamping is applied later at
        # prediction time. Reporting it on rejected sweeps too is what shows
        # whether a bad sweep was off-colour or just off.
        if "sky_red_over_green" in details:
            ratio_by_sweep[key].append(details["sky_red_over_green"])
        if annotation.get("use_for_factory_fit", False):
            # The zero point that would have made this frame match its
            # reference exactly. Independent of whichever model is shipped,
            # so it is the right quantity to fit either model against.
            implied = (
                reference - 2.5 * math.log10(exposure_sec) + 2.5 * math.log10(density)
            )
            fitted_zero_points[row["profile"]].append(implied)
            implied_by_sweep[key].append(implied)

    sweep_rows = []
    for (profile, sweep), errors in sorted(results.items()):
        quality_key = sweep_keys.get(sweep)
        annotation = quality.get(quality_key, {})
        ratios = ratio_by_sweep.get((profile, sweep), [])
        row_out = {
            "profile": profile,
            "sweep": sweep,
            "frames": len(errors),
            "median_error": statistics.median(errors),
            "frame_scatter": statistics.pstdev(errors) if len(errors) > 1 else 0.0,
            "condition": annotation.get("condition", "unreviewed"),
            "use_for_factory_fit": annotation.get("use_for_factory_fit", False),
            "quality_note": annotation.get("note", ""),
        }
        if ratios:
            # median_error above is already colour-corrected on these sweeps.
            row_out["median_red_over_green"] = float(statistics.median(ratios))
        sweep_rows.append(row_out)
    # Reduce each sweep to one point, then fit and cross-validate per profile.
    points_by_profile = defaultdict(list)
    for (profile, sweep), values in sorted(implied_by_sweep.items()):
        ratios = ratio_by_sweep.get((profile, sweep), [])
        points_by_profile[profile].append(
            SweepPoint(
                sweep=sweep,
                night=_night(sweep),
                implied_zero_point=float(statistics.median(values)),
                # A sweep counts as coloured only if every accepted frame
                # reported colour; a partial sweep would mix two populations.
                red_over_green=(
                    float(statistics.median(ratios))
                    if len(ratios) == len(values)
                    else None
                ),
            )
        )

    models = {}
    for profile, points in sorted(points_by_profile.items()):
        shipped = get_camera_profile(profile)
        # Profiles that ship no colour model carry pivot 0.0; let the fit pick
        # its own pivot there so the exploratory intercept is quoted at a real
        # sky colour rather than at R/G = 0.
        evaluation = evaluate_profile(points, shipped.radiometric_colour_pivot or None)
        evaluation["shipped"] = {
            "radiometric_zero_point": shipped.radiometric_zero_point,
            "radiometric_colour_slope": shipped.radiometric_colour_slope,
            "radiometric_colour_pivot": shipped.radiometric_colour_pivot,
            "radiometric_colour_range": list(shipped.radiometric_colour_range),
            "model": "colour" if shipped.radiometric_colour_slope else "constant",
        }
        evaluation["agrees_with_shipped"] = (
            evaluation["verdict"] == evaluation["shipped"]["model"]
        )
        models[profile] = evaluation

    output = {
        "sweeps": sweep_rows,
        # Constant-only fit, retained for continuity with earlier runs. It is
        # the shipped model only where radiometric_colour_slope is 0; compare
        # radiometric_models before quoting it as a factory value.
        "fitted_radiometric_zero_points": {
            profile: {
                "frames": len(values),
                "median": statistics.median(values),
                "scatter": statistics.pstdev(values),
            }
            for profile, values in fitted_zero_points.items()
        },
        "radiometric_models": models,
        "missing": missing,
    }
    rendered = json.dumps(output, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
