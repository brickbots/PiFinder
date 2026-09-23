#!/usr/bin/env python3
"""Replay the archive through the production SQM path.

One replay for every branch. Each archived frame becomes a radiometer sample
and goes through the device's own ``solver.update_radiometric_sqm``, so the
pedestal choice, the optical black, the airglow floor, the black-level tracker,
the publish cadence and the optics correction are whatever the checked-out code
does. Nothing here re-implements them.

Features are used when both the code and the frame have them, and reported in
provenance.json:

- ``analogue-gain``: the delivered AnalogueGain from frame_metadata.json.
- ``optical-black``: the measured optical black, by the production rule in
  ``camera_pi.optical_black_pedestal``. Stock stacks report none.
- ``airglow``: the airglow floor tracker, created as production does
  (IMX462 only).
- ``black-level-tracker``: the tracked black level.

``--disable FEATURE`` turns one off for comparison, for example
``--disable airglow`` for the factory path without the floor.

The stellar diagnostic that update_sqm hands to the radiometer (cloud flag,
transmission deficit, optics candidate) is rebuilt from the stellar CSV of
the archive harness at production's 10-second cadence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from PiFinder import solver
from PiFinder.sqm import SQM
from PiFinder.sqm.black_level import BlackLevelTracker
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.clouds import CloudEstimator
from PiFinder.sqm.radiometer import RadiometerAccumulator, collect_radiometer_sample
from PiFinder.state import SQM as SQMState

try:
    from PiFinder.camera_pi import optical_black_pedestal
except ImportError:  # branch without the optical-black patch
    optical_black_pedestal = None
try:
    from PiFinder.sqm.airglow import AirglowTracker
except ImportError:  # branch without the airglow floor
    AirglowTracker = None

FEATURES = ("analogue-gain", "optical-black", "airglow", "black-level-tracker")
_COLLECT = inspect.signature(collect_radiometer_sample).parameters
_UPDATE = inspect.signature(solver.update_radiometric_sqm).parameters
SUPPORTED = {
    "analogue-gain": "analogue_gain" in _COLLECT,
    "optical-black": "optical_black_pedestal" in _COLLECT
    and optical_black_pedestal is not None,
    "airglow": AirglowTracker is not None and "airglow_tracker" in _UPDATE,
    "black-level-tracker": "black_level_tracker" in _UPDATE,
}


class ReplayState:
    """The part of shared_state that update_radiometric_sqm touches.

    Production stamps last_update with the wall clock and compares it with the
    frame time on the next call. The replay keeps replay time instead, or the
    publish cadence would never reopen.
    """

    def __init__(self):
        self.now = 0.0
        self._details: dict = {}
        self._sqm = SQMState()

    def sqm_details(self) -> dict:
        return dict(self._details)

    def set_sqm_details(self, details: dict) -> None:
        self._details = dict(details)

    def sqm(self):
        return self._sqm

    def set_sqm(self, state) -> None:
        state.last_update = datetime.fromtimestamp(
            self.now, tz=timezone.utc
        ).isoformat()
        self._sqm = state


def _frame_metadata(sweep: Path) -> dict[int, dict]:
    path = Path(sweep) / "frame_metadata.json"
    if not path.exists():
        return {}
    try:
        return {
            int(frame["index"]): frame.get("camera_metadata") or {}
            for frame in json.loads(path.read_text())["frames"]
        }
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return {}


def _frame_index(frame_name: str):
    match = re.match(r"img_(\d+)", str(frame_name))
    return int(match.group(1)) if match else None


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
    parser.add_argument(
        "--disable",
        action="append",
        default=[],
        choices=FEATURES,
        help="turn a feature off for comparison; repeatable",
    )
    args = parser.parse_args()
    use = {name: SUPPORTED[name] and name not in args.disable for name in FEATURES}

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
    frames_with = {"analogue-gain": 0, "optical-black": 0}
    sequence = 0
    for (dataset, sweep_name), rows in sorted(grouped.items()):
        sweep = sweep_index[sweep_name]
        profile_name = rows[0]["profile"]
        profile = get_camera_profile(profile_name)
        annotation = quality.get(f"{dataset}/{sweep_name}", {})
        reference = _reference(rows[0], sweep)
        metadata = _frame_metadata(sweep)

        # A fresh session per sweep, created as the solver creates it.
        state = ReplayState()
        calculator = SQM(camera_type=profile_name)
        accumulator = RadiometerAccumulator()
        black = (
            BlackLevelTracker(profile.bias_offset)
            if use["black-level-tracker"]
            else None
        )
        airglow = (
            AirglowTracker(profile_name)
            if use["airglow"] and profile_name == "imx462"
            else None
        )
        cloud = CloudEstimator(
            clear_zero_point=profile.clear_zero_point,
            clear_sky_brightness=profile.clear_sky_brightness,
        )
        update_kwargs = {"black_level_tracker": black}
        if SUPPORTED["airglow"]:
            update_kwargs["airglow_tracker"] = airglow

        last_diagnostic_at = -math.inf
        published_values: list[float] = []
        uncorrected_values: list[float] = []
        stellar_values: list[float] = []
        correction_frames = cloud_flags = diagnostic_frames = 0
        radiometer_on_failed_solve = 0

        for frame_index, row in enumerate(rows):
            sequence += 1
            now = frame_index * args.assumed_frame_seconds
            state.now = now
            meta = metadata.get(_frame_index(row["frame"]), {})
            exposure_sec = float(row["exp_ms"]) / 1000.0

            extra = {}
            if use["analogue-gain"] and meta.get("AnalogueGain"):
                extra["analogue_gain"] = meta["AnalogueGain"]
                frames_with["analogue-gain"] += 1
            if use["optical-black"]:
                ob = optical_black_pedestal(meta, profile.bit_depth)
                if ob is not None:
                    extra["optical_black_pedestal"] = ob
                    frames_with["optical-black"] += 1
            sample = collect_radiometer_sample(
                np.asarray(Image.open(Path(row["raw_image"]))),
                profile,
                exposure_sec,
                sequence=sequence,
                captured_at=now,
                **extra,
            )

            published_now = solver.update_radiometric_sqm(
                state,
                calculator,
                accumulator,
                sample,
                calculation_interval_seconds=args.assumed_frame_seconds,
                now=now,
                **update_kwargs,
            )
            details = state.sqm_details()
            published = state.sqm().value if published_now else None
            radiometric = details.get("sqm_radiometric") if published_now else None
            corrected = bool(
                published_now
                and published is not None
                and radiometric is not None
                and abs(published - radiometric) > 1e-9
            )
            correction_frames += corrected

            solved = row["status"] == "ok" and bool(row.get("mzero"))
            if published is not None:
                published_values.append(published)
                uncorrected_values.append(float(radiometric))
                if not solved:
                    radiometer_on_failed_solve += 1

            # Stellar hand-off, as update_sqm does it after a solve, at most
            # once per 10 s: the uncorrected radiometric sky conditions it.
            diagnostic = False
            cloud_flag = deficit = None
            if solved and now - last_diagnostic_at >= 10.0:
                diagnostic = True
                diagnostic_frames += 1
                last_diagnostic_at = now
                stellar_values.append(float(row["sqm"]))
                sky = details.get("sqm_radiometric")
                if sky is None:
                    sky = state.sqm().value
                deficit = cloud.add_sample(
                    float(row["mzero"]),
                    exposure_sec,
                    sky_brightness=sky,
                    # The harness mzero already contains its rolling wing term.
                    wing_correction=0.0,
                    altitude_deg=float(row["altitude_deg"])
                    if row.get("altitude_deg")
                    else None,
                )
                cloud_flag = cloud.is_cloudy()
                cloud_flags += cloud_flag is True
                state.set_sqm_details(
                    {
                        **details,
                        "cloud_extinction": deficit,
                        "cloud_flag": cloud_flag,
                        "transmission_deficit": deficit,
                        "optics_attenuation_candidate": bool(
                            deficit is not None
                            and deficit > cloud.cloud_threshold
                            and cloud_flag is False
                            and cloud.conditioned()
                        ),
                        "transmission_diagnostic_at": now,
                    }
                )

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
                    "pedestal": details.get("pedestal"),
                    "pedestal_source": details.get("pedestal_source"),
                }
            )

        pedestal, pedestal_stderr, pedestal_samples = (
            black.state() if black is not None else (None, None, 0)
        )
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
        "features_supported_by_code": SUPPORTED,
        "features_used": use,
        "frames_with_feature_data": frames_with,
        "dark_current_calibrated": bool(
            getattr(calculator.noise_floor_estimator, "dark_current_calibrated", False)
        ),
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )

    lines = [
        "# Production SQM archive replay",
        "",
        "Every archived raw frame goes through the checked-out "
        "`solver.update_radiometric_sqm`, so this is whatever the code does. "
        "Publication is modeled at one frame per second. Solved stellar "
        "photometry is handed over at its production 10-second cadence.",
        "",
        "Features used: "
        + ", ".join(name for name in FEATURES if use[name])
        + ". Not used: "
        + (", ".join(name for name in FEATURES if not use[name]) or "none")
        + f". Frames with optical black: {frames_with['optical-black']}; "
        f"with analogue gain: {frames_with['analogue-gain']}.",
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
        ]
    )
    (args.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(args.output_dir)


if __name__ == "__main__":
    main()
