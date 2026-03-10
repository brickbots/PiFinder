"""
Telemetry session visualizer.

Generates a multi-panel figure from a PiFinder telemetry JSONL session:
  1. Sky track (RA/Dec) with solve vs IMU-predicted positions
  2. IMU drift: angular error between predicted and solved positions
  3. Solve success/failure timeline
  4. IMU free-run drift vs corrected (what happens without plate-solve correction)
  5. Solve cadence and RMSE over time
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import quaternion as npquat
from datetime import datetime, timezone, timedelta

# Add parent so we can import PiFinder modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing_model.astro_coords import RaDecRoll


def load_session(path):
    path = Path(path)
    header = None
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("e") == "hdr":
                header = obj
            else:
                events.append(obj)
    return header, events


def angular_separation(ra1, dec1, ra2, dec2):
    """Angular separation in arcminutes between two RA/Dec positions (degrees)."""
    ra1, dec1, ra2, dec2 = map(np.radians, [ra1, dec1, ra2, dec2])
    cos_sep = np.sin(dec1) * np.sin(dec2) + np.cos(dec1) * np.cos(dec2) * np.cos(
        ra1 - ra2
    )
    cos_sep = np.clip(cos_sep, -1, 1)
    return np.degrees(np.arccos(cos_sep)) * 60  # arcminutes


def events_to_times(events, t0, dt_start):
    """Convert event timestamps to datetime objects."""
    return [dt_start + timedelta(seconds=e["t"] - t0) for e in events]


def main(session_path):
    header, events = load_session(session_path)

    t0 = events[0]["t"]
    dt_start = datetime.fromisoformat(header["dt"]) if header and header.get("dt") else datetime.fromtimestamp(t0, tz=timezone.utc)

    solves = [e for e in events if e["e"] == "solve"]
    imus = [e for e in events if e["e"] == "imu"]
    successful = [s for s in solves if s.get("ra") is not None]
    failed = [s for s in solves if s.get("ra") is None]

    # --- Compute derived data ---

    # Solve times and positions
    solve_times = events_to_times(successful, t0, dt_start)
    solve_ras = [s["ra"] for s in successful]
    solve_decs = [s["dec"] for s in successful]

    # Failed solve times
    fail_times = events_to_times(failed, t0, dt_start)

    # IMU predictions vs actual solves (drift measurement)
    drift_solves = [s for s in successful if s.get("pred_ra") is not None]
    drift_times = events_to_times(drift_solves, t0, dt_start)
    drift_arcmin = [
        angular_separation(s["ra"], s["dec"], s["pred_ra"], s["pred_dec"])
        for s in drift_solves
    ]

    # RMSE values
    rmse_solves = [s for s in successful if s.get("rmse") is not None]
    rmse_times = events_to_times(rmse_solves, t0, dt_start)
    rmse_vals = [s["rmse"] for s in rmse_solves]

    # Match counts
    match_solves = [s for s in successful if s.get("matches") is not None]
    match_times = events_to_times(match_solves, t0, dt_start)
    match_vals = [s["matches"] for s in match_solves]

    # IMU quaternion norms (should be ~1.0)
    imu_with_q = [i for i in imus if i.get("q") is not None]
    imu_times = events_to_times(imu_with_q, t0, dt_start)
    quat_norms = [np.linalg.norm(i["q"]) for i in imu_with_q]

    # IMU movement detection
    imu_moving = [i.get("mv", False) for i in imu_with_q]

    # IMU rate (samples per second) - sliding window
    imu_ts = np.array([i["t"] for i in imu_with_q])
    window = 50
    imu_rates = []
    imu_rate_times = []
    for i in range(window, len(imu_ts)):
        dt_window = imu_ts[i] - imu_ts[i - window]
        if dt_window > 0:
            imu_rates.append(window / dt_window)
            imu_rate_times.append(
                dt_start + timedelta(seconds=imu_ts[i] - t0)
            )

    # --- Plot ---
    fig, axes = plt.subplots(5, 1, figsize=(14, 18), constrained_layout=True)

    duration_min = (events[-1]["t"] - t0) / 60
    fig.suptitle(
        f"Telemetry Session: {dt_start.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        f"  |  {duration_min:.1f} min"
        f"  |  {len(successful)}/{len(solves)} solves",
        fontsize=13,
        fontweight="bold",
    )

    # Panel 1: Sky track
    ax = axes[0]
    ax.plot(solve_ras, solve_decs, ".-", color="steelblue", markersize=4, alpha=0.7, label="Plate solves")
    if drift_solves:
        pred_ras = [s["pred_ra"] for s in drift_solves]
        pred_decs = [s["pred_dec"] for s in drift_solves]
        ax.scatter(pred_ras, pred_decs, c="orangered", s=12, alpha=0.5, zorder=5, label="IMU predicted")
        # Draw lines connecting prediction to actual
        for s in drift_solves:
            ax.plot(
                [s["pred_ra"], s["ra"]],
                [s["pred_dec"], s["dec"]],
                "-",
                color="orangered",
                alpha=0.15,
                linewidth=0.8,
            )
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.set_title("Sky Track: Solved vs IMU-Predicted Positions")
    ax.legend(loc="best", fontsize=9)
    ax.invert_xaxis()
    ax.grid(True, alpha=0.3)

    # Panel 2: IMU drift
    ax = axes[1]
    if drift_arcmin:
        ax.plot(drift_times, drift_arcmin, ".-", color="orangered", markersize=4, alpha=0.8)
        ax.axhline(y=np.median(drift_arcmin), color="gray", linestyle="--", alpha=0.5, label=f"Median: {np.median(drift_arcmin):.1f}'")
        p90 = np.percentile(drift_arcmin, 90)
        ax.axhline(y=p90, color="gray", linestyle=":", alpha=0.4, label=f"P90: {p90:.1f}'")
        ax.legend(loc="best", fontsize=9)
    ax.set_ylabel("Drift (arcmin)")
    ax.set_title("IMU Prediction Error (angular separation from plate solve)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.grid(True, alpha=0.3)

    # Panel 3: Solve timeline - success/fail + matches
    ax = axes[2]
    ax2 = ax.twinx()
    if solve_times:
        ax.scatter(solve_times, [1] * len(solve_times), c="limegreen", s=20, marker="|", linewidths=2, label=f"Success ({len(successful)})", zorder=5)
    if fail_times:
        ax.scatter(fail_times, [0] * len(fail_times), c="red", s=20, marker="|", linewidths=2, label=f"Failed ({len(failed)})", zorder=5)
    if match_vals:
        ax2.plot(match_times, match_vals, "-", color="steelblue", alpha=0.6, label="Matches")
        ax2.set_ylabel("Star matches", color="steelblue")
        ax2.tick_params(axis="y", labelcolor="steelblue")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Failed", "Success"])
    ax.set_title("Solve Timeline")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.legend(loc="upper left", fontsize=9)
    if match_vals:
        ax2.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 4: IMU free-run drift (what happens without plate-solve correction)
    ax = axes[3]
    ax_mv = ax.twinx()

    # Movement as background shading
    moving_arr = np.array(imu_moving, dtype=float)
    ax_mv.fill_between(imu_times, 0, moving_arr, color="orange", alpha=0.15, step="mid", label="Moving")
    ax_mv.set_ylabel("Moving", color="orange")
    ax_mv.set_yticks([0, 1])
    ax_mv.set_yticklabels(["Still", "Moving"])
    ax_mv.tick_params(axis="y", labelcolor="orange")

    # Compute free-run drift using ImuDeadReckoning
    solves_with_iq = [s for s in successful if s.get("iq") is not None and s.get("cam_ra") is not None]
    if len(solves_with_iq) >= 2:
        first = solves_with_iq[0]
        dr = ImuDeadReckoning("flat")
        cam0 = RaDecRoll()
        cam0.set_from_deg(first["cam_ra"], first["cam_dec"], first["cam_roll"])
        scope0 = RaDecRoll()
        scope0.set_from_deg(first["ra"], first["dec"], first.get("roll", 0))
        dr.set_cam2scope_alignment(cam0, scope0)
        q_first = npquat.from_float_array(first["iq"])
        dr.update_plate_solve_and_imu(cam0, q_first)
        # Initialize scope quaternion so get_scope_radec() works immediately
        dr.update_imu(q_first)

        # Dead-reckon through all IMU events, measure drift at each solve
        imu_iter = iter(i for i in imu_with_q if i["t"] > first["t"])
        freerun_drift_times = []
        freerun_drift_vals = []
        for s in solves_with_iq[1:]:
            # Feed IMU events up to this solve's time
            for imu_evt in imu_iter:
                if imu_evt["t"] > s["t"]:
                    break
                dr.update_imu(npquat.from_float_array(imu_evt["q"]))
            radec = dr.get_scope_radec()
            ra_deg, dec_deg, _ = radec.get_deg(use_none=True)
            if ra_deg is not None:
                sep = angular_separation(ra_deg, dec_deg, s["ra"], s["dec"])
                freerun_drift_times.append(
                    dt_start + timedelta(seconds=s["t"] - t0)
                )
                freerun_drift_vals.append(sep)

        if freerun_drift_vals:
            ax.plot(freerun_drift_times, freerun_drift_vals, ".-", color="orangered",
                    markersize=3, alpha=0.8, label="Free-run (no correction)")
            # Also show corrected drift for comparison
            if drift_arcmin:
                ax.plot(drift_times, drift_arcmin, ".-", color="steelblue",
                        markersize=3, alpha=0.6, label="Corrected each solve")
            ax.set_ylabel("Drift from truth (arcmin)")
            median_fr = np.median(freerun_drift_vals)
            max_fr = max(freerun_drift_vals)
            ax.set_title(
                f"IMU Free-Run Drift vs Corrected"
                f"  |  Free-run: median {median_fr:.0f}', max {max_fr:.0f}'"
            )
            ax.legend(loc="upper left", fontsize=9)
    else:
        ax.set_title("IMU Free-Run Drift (insufficient data)")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax_mv.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 5: RMSE + IMU sample rate
    ax = axes[4]
    ax_rate = ax.twinx()
    if rmse_vals:
        ax.plot(rmse_times, rmse_vals, ".-", color="purple", markersize=3, alpha=0.7, label="RMSE")
        ax.set_ylabel("Solve RMSE", color="purple")
        ax.tick_params(axis="y", labelcolor="purple")
    if imu_rates:
        ax_rate.plot(imu_rate_times, imu_rates, "-", color="teal", alpha=0.4, linewidth=0.8, label="IMU rate")
        ax_rate.set_ylabel("IMU sample rate (Hz)", color="teal")
        ax_rate.tick_params(axis="y", labelcolor="teal")
        ax_rate.legend(loc="upper right", fontsize=9)
    ax.set_xlabel("Time (UTC)")
    ax.set_title("Solve RMSE & IMU Sample Rate")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Save
    out_path = Path(session_path).parent / "telemetry_viz.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")

    # Print stats
    print(f"\n--- Session Stats ---")
    print(f"Duration: {duration_min:.1f} min")
    print(f"Solves: {len(successful)}/{len(solves)} ({100*len(successful)/len(solves):.0f}% success rate)")
    print(f"IMU events: {len(imus)} ({len(imus)/(events[-1]['t']-t0):.1f} Hz avg)")
    print(f"Moving events: {sum(imu_moving)}/{len(imu_with_q)} ({100*sum(imu_moving)/len(imu_with_q):.1f}%)")
    if drift_arcmin:
        print(f"IMU drift: median {np.median(drift_arcmin):.1f}', mean {np.mean(drift_arcmin):.1f}', P90 {np.percentile(drift_arcmin, 90):.1f}', max {max(drift_arcmin):.1f}'")
    if rmse_vals:
        print(f"Solve RMSE: median {np.median(rmse_vals):.3f}, mean {np.mean(rmse_vals):.3f}")
    if quat_norms:
        print(f"Quat norm: mean {np.mean(quat_norms):.6f}, std {np.std(quat_norms):.6f}")
    if match_vals:
        print(f"Star matches: median {np.median(match_vals):.0f}, min {min(match_vals)}, max {max(match_vals)}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(Path(__file__).parent / "session_20260309.jsonl")
