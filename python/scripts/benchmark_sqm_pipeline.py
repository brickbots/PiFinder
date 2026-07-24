#!/usr/bin/env python3
"""Reproducible SQM/solver micro-benchmark on archived sweep frames.

The benchmark loads images before timing so storage and TIFF/PNG decoding do not
pollute the CPU measurements.  It is intended for before/after comparisons of
the same checkout, machine, archive sweep, frame count, and repeat count.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import time
from pathlib import Path
from typing import Callable

import numpy as np
import tetra3
from PIL import Image

from PiFinder.solver import _extract_raw_photometry_image, _scale_solution_centroids
from PiFinder.sqm import SQM
from PiFinder.sqm.radiometer import collect_radiometer_sample


EXPOSURE_RE = re.compile(r"_(\d+(?:\.\d+)?)ms_")


def _duration_ms(
    operation: Callable[[], object], repeats: int
) -> tuple[object, list[float]]:
    result = operation()  # warm caches and validate once outside the samples
    samples = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        result = operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return result, samples


def _summary(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    p95_index = max(0, int(np.ceil(0.95 * len(ordered))) - 1)
    return {
        "samples": len(samples),
        "median_ms": statistics.median(ordered),
        "mean_ms": statistics.fmean(ordered),
        "p95_ms": ordered[p95_index],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def _native_solver_image(
    raw: np.ndarray, bit_depth: int, pedestal: float
) -> np.ndarray:
    """Apply the production linear stretch without its final 512px resize."""
    linear = raw.astype(np.float32) - pedestal
    linear *= 255.0 / (2**bit_depth - pedestal - 1)
    return np.clip(linear, 0, 255).astype(np.uint8)


def _paired_paths(sweep: Path, frame_count: int) -> list[tuple[Path, Path]]:
    pairs = []
    for processed in sorted(sweep.glob("*_processed.png")):
        prefix = processed.name.removesuffix("_processed.png")
        raw_matches = sorted(sweep.glob(f"{prefix}_raw*.tiff"))
        if raw_matches:
            pairs.append((processed, raw_matches[0]))
        if len(pairs) >= frame_count:
            break
    if not pairs:
        raise SystemExit(f"No processed/raw TIFF pairs found in {sweep}")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sweep", type=Path)
    parser.add_argument("--sensor", required=True)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.WARNING)
    profile = SQM(camera_type=args.sensor).profile
    pairs = _paired_paths(args.sweep, args.frames)
    loaded = [
        (
            processed,
            np.asarray(Image.open(processed).convert("L")),
            np.asarray(Image.open(raw)),
        )
        for processed, raw in pairs
    ]
    t3 = tetra3.Tetra3("default_database")
    sqm = SQM(camera_type=args.sensor)

    timings: dict[str, list[float]] = {
        "raw_green_extract": [],
        "radiometer_collect": [],
        "full_green_median": [],
        "native_solver_preprocess": [],
        "green_solver_preprocess": [],
        "centroid_512": [],
        "centroid_native": [],
        "centroid_green": [],
        "solve_512": [],
        "solve_native": [],
        "solve_green": [],
        "star_calibrated_sqm": [],
    }
    frame_results = []

    for processed_path, processed, raw in loaded:
        exposure_match = EXPOSURE_RE.search(processed_path.name)
        exposure_sec = float(exposure_match.group(1)) / 1000.0
        _, samples = _duration_ms(
            lambda raw=raw, exposure_sec=exposure_sec: collect_radiometer_sample(
                raw,
                profile,
                exposure_sec,
                sequence=1,
                captured_at=1.0,
            ),
            args.repeats,
        )
        timings["radiometer_collect"].extend(samples)
        green, samples = _duration_ms(
            lambda raw=raw: _extract_raw_photometry_image(raw, profile), args.repeats
        )
        timings["raw_green_extract"].extend(samples)
        if green is None:
            continue

        _, samples = _duration_ms(lambda: float(np.median(green)), args.repeats)
        timings["full_green_median"].extend(samples)

        native, samples = _duration_ms(
            lambda raw=raw: _native_solver_image(
                raw, profile.bit_depth, profile.bias_offset
            ),
            args.repeats,
        )
        timings["native_solver_preprocess"].extend(samples)
        green_solver, samples = _duration_ms(
            lambda green=green: _native_solver_image(
                green, profile.bit_depth, profile.bias_offset
            ),
            args.repeats,
        )
        timings["green_solver_preprocess"].extend(samples)

        centroids_512, samples = _duration_ms(
            lambda processed=processed: tetra3.get_centroids_from_image(processed),
            args.repeats,
        )
        timings["centroid_512"].extend(samples)
        centroids_native, samples = _duration_ms(
            lambda native=native: tetra3.get_centroids_from_image(native), args.repeats
        )
        timings["centroid_native"].extend(samples)
        centroids_green, samples = _duration_ms(
            lambda green_solver=green_solver: tetra3.get_centroids_from_image(
                green_solver
            ),
            args.repeats,
        )
        timings["centroid_green"].extend(samples)

        solve_args = {
            "fov_estimate": 12.0,
            "fov_max_error": 4.0,
            "match_max_error": 0.005,
            "return_matches": True,
            "solve_timeout": 1000,
        }
        solution_512, samples = _duration_ms(
            lambda: t3.solve_from_centroids(
                centroids_512, processed.shape, **solve_args
            ),
            args.repeats,
        )
        timings["solve_512"].extend(samples)
        solution_native, samples = _duration_ms(
            lambda: t3.solve_from_centroids(
                centroids_native, native.shape, **solve_args
            ),
            args.repeats,
        )
        timings["solve_native"].extend(samples)
        solution_green, samples = _duration_ms(
            lambda: t3.solve_from_centroids(
                centroids_green, green_solver.shape, **solve_args
            ),
            args.repeats,
        )
        timings["solve_green"].extend(samples)

        sqm_value = None
        if solution_512.get("matched_centroids") is not None:
            scale = green.shape[0] / processed.shape[0]
            calc_solution = _scale_solution_centroids(solution_512, scale)
            calc_centroids = np.asarray(centroids_512) * scale

            def operation():
                return sqm.calculate(
                    centroids=calc_centroids,
                    solution=calc_solution,
                    image=green,
                    exposure_sec=exposure_sec,
                    saturation_threshold=int(0.70 * (2**profile.bit_depth - 1)),
                    image_pixels_per_side=green.shape[0],
                )

            (sqm_value, _), samples = _duration_ms(operation, args.repeats)
            timings["star_calibrated_sqm"].extend(samples)

        frame_results.append(
            {
                "frame": processed_path.name,
                "processed_shape": list(processed.shape),
                "raw_shape": list(raw.shape),
                "green_shape": list(green.shape),
                "centroids_512": len(centroids_512),
                "centroids_native": len(centroids_native),
                "centroids_green": len(centroids_green),
                "matches_512": int(solution_512.get("Matches") or 0),
                "matches_native": int(solution_native.get("Matches") or 0),
                "matches_green": int(solution_green.get("Matches") or 0),
                "sqm": sqm_value,
            }
        )

    result = {
        "sweep": str(args.sweep),
        "sensor": args.sensor,
        "frames": len(frame_results),
        "repeats": args.repeats,
        "timings": {
            name: _summary(values) for name, values in timings.items() if values
        },
        "frame_results": frame_results,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
