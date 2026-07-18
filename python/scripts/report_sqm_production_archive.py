#!/usr/bin/env python3
"""Replay and report the current radiometer-first production SQM pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from PiFinder.sqm.black_level import BlackLevelTracker
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.clouds import CloudEstimator
from PiFinder.sqm.radiometer import RadiometerAccumulator, collect_radiometer_sample


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(row: dict[str, str], sweep: Path) -> float | None:
    if row.get("reference_sqm"):
        return float(row["reference_sqm"])
    metadata = sweep / "sweep_metadata.json"
    if metadata.exists():
        value = json.loads(metadata.read_text()).get("reference_sqm")
        if value is not None:
            return float(value)
    if sweep.name == "sweep_20251031_195434":
        return 17.85
    return None


def _metrics(errors: list[float]) -> dict[str, float | int]:
    return {
        "sweeps": len(errors),
        "bias": statistics.fmean(errors),
        "residual_sigma": statistics.pstdev(errors) if len(errors) > 1 else 0.0,
        "mae": statistics.fmean(abs(value) for value in errors),
        "rmse": math.sqrt(statistics.fmean(value * value for value in errors)),
    }


def _fmt(value, digits: int = 3) -> str:
    return "" if value is None else f"{float(value):.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stellar_csv", type=Path)
    parser.add_argument("sweeps", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--quality", type=Path)
    parser.add_argument(
        "--assumed-frame-seconds",
        type=float,
        default=1.0,
        help="Archive has no capture timestamps; default models one new frame/second.",
    )
    args = parser.parse_args()

    quality_path = args.quality or args.sweeps / "sqm_archive_quality.json"
    quality = json.loads(quality_path.read_text())
    sweep_index = {
        path.name: path for path in args.sweeps.glob("*/sweep_*") if path.is_dir()
    }

    # The stellar harness emits two background variants per input frame. The
    # local-annulus row is production and, including failures, is one-to-one
    # with archived raw frames.
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with args.stellar_csv.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["variant"] == "local_annulus":
                grouped[(row["dataset"], row["sweep"])].append(row)

    frame_rows: list[dict] = []
    sweep_rows: list[dict] = []
    sequence = 0
    for (dataset, sweep_name), rows in sorted(grouped.items()):
        sweep = sweep_index[sweep_name]
        profile_name = rows[0]["profile"]
        profile = get_camera_profile(profile_name)
        annotation = quality.get(f"{dataset}/{sweep_name}", {})
        reference = _reference(rows[0], sweep)
        accumulator = RadiometerAccumulator()
        cloud = CloudEstimator(
            clear_zero_point=profile.clear_zero_point,
            clear_sky_brightness=profile.clear_sky_brightness,
        )
        black = BlackLevelTracker(profile.bias_offset)
        last_cloud_flag = None
        last_diagnostic_at = -math.inf
        candidate_deficit = None
        candidate_at = None
        published_values: list[float] = []
        uncorrected_values: list[float] = []
        stellar_values: list[float] = []
        correction_frames = 0
        cloud_flags = 0
        diagnostic_frames = 0
        radiometer_on_failed_solve = 0

        for frame_index, row in enumerate(rows):
            sequence += 1
            now = frame_index * args.assumed_frame_seconds
            raw_path = Path(row["raw_image"])
            raw = np.asarray(Image.open(raw_path))
            exposure_sec = float(row["exp_ms"]) / 1000.0
            sample = collect_radiometer_sample(
                raw,
                profile,
                exposure_sec,
                sequence=sequence,
                captured_at=now,
            )
            if accumulator.add(sample):
                # Production feeds the tracker from every fresh radiometer
                # sample, withheld while the last diagnostic said cloud.
                black.add_sample(
                    float(sample["exposure_sec"]),
                    float(sample["background_per_pixel"]),
                    stable=last_cloud_flag is not True,
                )

            def pedestal_for_exposure(_exposure_sec):
                tracked = black.pedestal()
                return tracked if tracked is not None else profile.bias_offset

            radiometric, details = accumulator.estimate(
                profile, now, pedestal_for_exposure=pedestal_for_exposure
            )
            published = radiometric
            corrected = False
            if (
                published is not None
                and candidate_deficit is not None
                and candidate_at is not None
                and 0 <= now - candidate_at <= 15.0
                and 0.0 < candidate_deficit <= 2.0
            ):
                published -= candidate_deficit
                corrected = True
                correction_frames += 1

            solved = row["status"] == "ok" and bool(row.get("mzero"))
            if published is not None:
                published_values.append(published)
                uncorrected_values.append(float(radiometric))
                if not solved:
                    radiometer_on_failed_solve += 1

            diagnostic = False
            cloud_flag = None
            deficit = None
            if solved and now - last_diagnostic_at >= 10.0:
                diagnostic = True
                diagnostic_frames += 1
                last_diagnostic_at = now
                stellar_values.append(float(row["sqm"]))
                deficit = cloud.add_sample(
                    float(row["mzero"]),
                    exposure_sec,
                    # Uncorrected: correction feedback must not read as excess.
                    sky_brightness=radiometric,
                    # The harness mzero already contains its rolling wing term.
                    wing_correction=0.0,
                    altitude_deg=float(row["altitude_deg"])
                    if row.get("altitude_deg")
                    else None,
                )
                cloud_flag = cloud.is_cloudy()
                cloud_flags += cloud_flag is True
                last_cloud_flag = cloud_flag
                if (
                    deficit is not None
                    and deficit > cloud.cloud_threshold
                    and cloud_flag is False
                    and cloud.conditioned()
                ):
                    candidate_deficit = float(deficit)
                    candidate_at = now
                else:
                    candidate_deficit = None
                    candidate_at = now

            frame_rows.append(
                {
                    "dataset": dataset,
                    "sweep": sweep_name,
                    "frame": row["frame"],
                    "profile": profile_name,
                    "exposure_ms": float(row["exp_ms"]),
                    "solve_ok": solved,
                    "radiometric_uncorrected": radiometric,
                    "published_sqm": published,
                    "reference_sqm": reference,
                    "error": published - reference
                    if published is not None and reference is not None
                    else None,
                    "stellar_diagnostic": diagnostic,
                    "stellar_sqm": float(row["sqm"]) if solved else None,
                    "transmission_deficit": deficit,
                    "cloud_flag": cloud_flag,
                    "optics_correction_applied": corrected,
                    "radiometer_samples": details.get("radiometer_samples"),
                }
            )

        pedestal, pedestal_stderr, pedestal_samples = black.state()
        median_published = (
            statistics.median(published_values) if published_values else None
        )
        median_uncorrected = (
            statistics.median(uncorrected_values) if uncorrected_values else None
        )
        median_stellar = statistics.median(stellar_values) if stellar_values else None
        sweep_rows.append(
            {
                "dataset": dataset,
                "sweep": sweep_name,
                "profile": profile_name,
                "condition": annotation.get("condition", "unreviewed"),
                "use_for_factory_fit": annotation.get("use_for_factory_fit", False),
                "frames": len(rows),
                "radiometer_frames": len(published_values),
                "failed_solve_radiometer_frames": radiometer_on_failed_solve,
                "diagnostic_frames": diagnostic_frames,
                "cloud_flags": cloud_flags,
                "correction_frames": correction_frames,
                "reference_sqm": reference,
                "median_published_sqm": median_published,
                "median_uncorrected_sqm": median_uncorrected,
                "median_stellar_sqm": median_stellar,
                "median_error": median_published - reference
                if median_published is not None and reference is not None
                else None,
                "frame_scatter": statistics.pstdev(published_values)
                if len(published_values) > 1
                else None,
                "tracked_pedestal": pedestal,
                "tracked_pedestal_stderr": pedestal_stderr,
                "tracked_pedestal_samples": pedestal_samples,
                "quality_note": annotation.get("note", ""),
            }
        )

    accepted = [
        row
        for row in sweep_rows
        if row["use_for_factory_fit"] and row["median_error"] is not None
    ]
    overall = _metrics([float(row["median_error"]) for row in accepted])
    by_profile = {
        profile: _metrics(
            [
                float(row["median_error"])
                for row in accepted
                if row["profile"] == profile
            ]
        )
        for profile in sorted({row["profile"] for row in accepted})
    }
    continuity = {
        "archive_frames": len(frame_rows),
        "radiometer_publications": sum(row["radiometer_frames"] for row in sweep_rows),
        "publications_on_failed_solve_frames": sum(
            row["failed_solve_radiometer_frames"] for row in sweep_rows
        ),
        "stellar_diagnostics": sum(row["diagnostic_frames"] for row in sweep_rows),
        "optics_corrected_frames": sum(row["correction_frames"] for row in sweep_rows),
    }

    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "per_frame.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(frame_rows[0]))
        writer.writeheader()
        writer.writerows(frame_rows)
    with (args.output_dir / "sweep_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(sweep_rows[0]))
        writer.writeheader()
        writer.writerows(sweep_rows)

    results = {
        "overall": overall,
        "by_profile": by_profile,
        "continuity": continuity,
        "assumptions": {
            "frame_seconds": args.assumed_frame_seconds,
            "publish_cadence_seconds": 1.0,
            "stellar_diagnostic_cadence_seconds": 10.0,
            "diagnostic_expiry_seconds": 15.0,
            "session_model": "each archived sweep starts a fresh runtime session",
        },
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n"
    )
    provenance = {
        "created_at": datetime.now().astimezone().isoformat(),
        "stellar_csv": str(args.stellar_csv.resolve()),
        "stellar_csv_sha256": _sha256(args.stellar_csv),
        "quality_manifest": str(quality_path.resolve()),
        "quality_manifest_sha256": _sha256(quality_path),
        "script_sha256": _sha256(Path(__file__)),
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )

    lines = [
        "# Latest production SQM archive replay",
        "",
        "This is the current zero-touch, radiometer-first `deepchart` path. "
        "Every archived raw frame feeds the 12-sample/15-second accumulator; "
        "publication is modeled at 1 Hz. Solved stellar photometry is sampled "
        "at its production 10-second cadence and is diagnostic-only.",
        "",
        "## Expected out-of-box accuracy",
        "",
        "One median per independently reviewed factory-eligible sweep:",
        "",
        "| Population | Sweeps | Bias | Residual σ | MAE | RMSE |",
        "|---|---:|---:|---:|---:|---:|",
        f"| All accepted | {overall['sweeps']} | {overall['bias']:.3f} | "
        f"{overall['residual_sigma']:.3f} | {overall['mae']:.3f} | "
        f"{overall['rmse']:.3f} |",
    ]
    for profile, item in by_profile.items():
        lines.append(
            f"| {profile} | {item['sweeps']} | {item['bias']:.3f} | "
            f"{item['residual_sigma']:.3f} | {item['mae']:.3f} | "
            f"{item['rmse']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Runtime continuity",
            "",
            f"- Radiometer publications: {continuity['radiometer_publications']}/"
            f"{continuity['archive_frames']} archived frames.",
            f"- Publications on frames without usable stellar photometry: "
            f"{continuity['publications_on_failed_solve_frames']}.",
            f"- Ten-second stellar diagnostics: {continuity['stellar_diagnostics']}.",
            f"- Automatic optics-corrected publications in this replay: "
            f"{continuity['optics_corrected_frames']}.",
            "",
            "## Per-sweep results",
            "",
            "| Sweep | Sensor | Reviewed condition | Used | Frames | Failed-solve "
            "continuity | Reference | Median | Error | Frame σ | Corrections |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sweep_rows:
        lines.append(
            f"| {row['sweep']} | {row['profile']} | {row['condition']} | "
            f"{'yes' if row['use_for_factory_fit'] else 'no'} | {row['frames']} | "
            f"{row['failed_solve_radiometer_frames']} | "
            f"{_fmt(row['reference_sqm'], 2)} | {_fmt(row['median_published_sqm'])} | "
            f"{_fmt(row['median_error'])} | {_fmt(row['frame_scatter'])} | "
            f"{row['correction_frames']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation and limits",
            "",
            "The headline measures the factory constants on the same sweeps used "
            "to fit them; it is an in-sample acceptance result, not independent "
            "dark-site or unit-to-unit validation. IMX296 still has only one "
            "moonlit, vertically banded reference sweep.",
            "",
            "The archive has frame order but no trustworthy capture timestamps. "
            "The cadence replay therefore assumes one new frame per second and a "
            "fresh runtime session per sweep. The primary radiometer values do not "
            "depend on solves or this timing assumption; rolling scatter and the "
            "cloud/dew correction opportunity do.",
            "",
            "The black-level tracker currently refines the stellar diagnostic "
            "pedestal only. It does not feed the published radiometer pedestal, so "
            "it cannot improve the headline out-of-box SQM numbers in this code.",
        ]
    )
    (args.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(args.output_dir)


if __name__ == "__main__":
    main()
