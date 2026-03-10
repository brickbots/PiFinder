"""
IMU Free-Running Drift Analysis.

Dead-reckon forward from the first successful plate solve using only IMU
quaternion deltas — never reset from subsequent plate solves.  Compare the
free-running trajectory against actual plate-solved positions to show how
much the IMU drifts when "left to its own devices."
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import quaternion as quat

# Add parent so we can import PiFinder modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing_model.astro_coords import RaDecRoll
import PiFinder.pointing_model.quaternion_transforms as qt


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


def angular_separation_arcmin(ra1, dec1, ra2, dec2):
    """Angular separation in arcminutes (inputs in degrees)."""
    ra1, dec1, ra2, dec2 = map(np.radians, [ra1, dec1, ra2, dec2])
    cos_sep = np.sin(dec1) * np.sin(dec2) + np.cos(dec1) * np.cos(dec2) * np.cos(
        ra1 - ra2
    )
    return np.degrees(np.arccos(np.clip(cos_sep, -1, 1))) * 60


def main(session_path):
    header, events = load_session(session_path)
    t0 = events[0]["t"]

    solves = [e for e in events if e["e"] == "solve"]
    imus = [e for e in events if e["e"] == "imu"]
    successful = [s for s in solves if s.get("ra") is not None and s.get("iq") is not None]

    if len(successful) < 2:
        print("Need at least 2 successful solves with IMU quaternions")
        return

    # --- Set up dead-reckoning from first solve, never correct again ---
    first = successful[0]
    screen_direction = "flat"  # PiFinder v2 default

    dr = ImuDeadReckoning(screen_direction)

    # Set camera-to-scope alignment
    cam = RaDecRoll()
    cam.set_from_deg(first["cam_ra"], first["cam_dec"], first["cam_roll"])
    scope = RaDecRoll()
    scope.set_from_deg(first["ra"], first["dec"], first.get("roll", 0))
    dr.set_cam2scope_alignment(cam, scope)

    # Initialize with first plate solve + IMU quaternion
    q_first = quat.from_float_array(first["iq"])
    dr.update_plate_solve_and_imu(cam, q_first)

    # --- Process all IMU events: dead-reckon without correction ---
    freerun_times = []
    freerun_ra = []
    freerun_dec = []

    for imu_evt in imus:
        if imu_evt["t"] < first["t"]:
            continue
        q_imu = quat.from_float_array(imu_evt["q"])
        dr.update_imu(q_imu)
        radec = dr.get_scope_radec()
        ra_deg, dec_deg, _ = radec.get_deg(use_none=True)
        if ra_deg is not None:
            freerun_times.append(imu_evt["t"] - t0)
            freerun_ra.append(ra_deg)
            freerun_dec.append(dec_deg)

    # --- Actual plate-solved positions ---
    solve_times = [(s["t"] - t0) for s in successful]
    solve_ra = [s["ra"] for s in successful]
    solve_dec = [s["dec"] for s in successful]

    # --- Compute drift at each plate-solve time ---
    # For each solve, find the closest free-run sample
    freerun_t_arr = np.array(freerun_times)
    drift_times = []
    drift_arcmin = []
    drift_ra_deg = []
    drift_dec_deg = []

    for s in successful[1:]:  # skip first (zero drift by definition)
        st = s["t"] - t0
        idx = np.argmin(np.abs(freerun_t_arr - st))
        fr_ra = freerun_ra[idx]
        fr_dec = freerun_dec[idx]
        sep = angular_separation_arcmin(fr_ra, fr_dec, s["ra"], s["dec"])
        drift_times.append(st)
        drift_arcmin.append(sep)
        drift_ra_deg.append(fr_ra - s["ra"])
        drift_dec_deg.append(fr_dec - s["dec"])

    # --- Also compute "normal mode" drift (corrected each solve) ---
    dr_corrected = ImuDeadReckoning(screen_direction)
    dr_corrected.set_cam2scope_alignment(cam, scope)
    dr_corrected.update_plate_solve_and_imu(cam, q_first)

    corrected_drift = []
    last_solve_idx = 0
    for i, s in enumerate(successful[1:], 1):
        # Feed IMU events between this solve and the previous one
        q_imu = quat.from_float_array(s["iq"])
        dr_corrected.update_imu(q_imu)
        radec = dr_corrected.get_scope_radec()
        ra_deg, dec_deg, _ = radec.get_deg(use_none=True)
        if ra_deg is not None:
            sep = angular_separation_arcmin(ra_deg, dec_deg, s["ra"], s["dec"])
            corrected_drift.append(sep)
        else:
            corrected_drift.append(0)
        # Now correct with this plate solve
        cam_s = RaDecRoll()
        cam_s.set_from_deg(s["cam_ra"], s["cam_dec"], s["cam_roll"])
        dr_corrected.update_plate_solve_and_imu(cam_s, q_imu)

    # --- Plot ---
    fig, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
    fig.suptitle(
        "IMU Free-Running Drift: What Happens Without Plate Solve Correction?",
        fontsize=13,
        fontweight="bold",
    )

    # Convert to minutes
    fr_t_min = [t / 60 for t in freerun_times]
    s_t_min = [t / 60 for t in solve_times]
    d_t_min = [t / 60 for t in drift_times]

    # Panel 1: Sky track — free-run vs actual
    ax = axes[0, 0]
    ax.plot(freerun_ra, freerun_dec, "-", color="orangered", alpha=0.5, linewidth=0.5,
            label="IMU free-run (no correction)")
    ax.plot(solve_ra, solve_dec, "o", color="steelblue", markersize=4, alpha=0.8,
            label="Plate solves (truth)")
    ax.plot(solve_ra[0], solve_dec[0], "*", color="green", markersize=12,
            label="Start (shared)", zorder=5)
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.set_title("Sky Track: Free-Running IMU vs Plate Solves")
    ax.legend(fontsize=8)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.invert_xaxis()

    # Panel 2: Drift over time
    ax = axes[0, 1]
    ax.plot(d_t_min, drift_arcmin, "o-", color="orangered", markersize=3, alpha=0.7,
            label="Free-run drift")
    if corrected_drift:
        cd_t_min = d_t_min[:len(corrected_drift)]
        ax.plot(cd_t_min, corrected_drift, "s-", color="steelblue", markersize=3,
                alpha=0.7, label="Corrected-each-solve drift")
    ax.set_xlabel("Session time (min)")
    ax.set_ylabel("Drift from truth (arcmin)")
    ax.set_title("Drift Accumulation Over Time")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Panel 3: Drift direction (RA vs Dec error)
    ax = axes[1, 0]
    # Convert to arcmin for readability
    drift_ra_am = [d * 60 for d in drift_ra_deg]
    drift_dec_am = [d * 60 for d in drift_dec_deg]
    scatter = ax.scatter(drift_ra_am, drift_dec_am,
                         c=d_t_min, cmap="viridis", s=20, alpha=0.7)
    ax.axhline(0, color="gray", alpha=0.3)
    ax.axvline(0, color="gray", alpha=0.3)
    ax.plot(0, 0, "+", color="red", markersize=15, markeredgewidth=2)
    cb = plt.colorbar(scatter, ax=ax)
    cb.set_label("Time (min)", fontsize=8)
    ax.set_xlabel("RA drift (arcmin, free-run - truth)")
    ax.set_ylabel("Dec drift (arcmin, free-run - truth)")
    ax.set_title("Drift Direction Over Session\n(color = time)")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # Panel 4: Drift rate (arcmin per minute)
    ax = axes[1, 1]
    if len(drift_times) > 1:
        # Cumulative drift divided by elapsed time since start
        elapsed = [(t - drift_times[0]) / 60 for t in drift_times]
        rates = []
        for i, (e, d) in enumerate(zip(elapsed, drift_arcmin)):
            if e > 0:
                rates.append(d / e)
            else:
                rates.append(0)
        ax.plot(d_t_min[1:], rates[1:], "o-", color="teal", markersize=3, alpha=0.7)
        if len(rates) > 2:
            median_rate = np.median(rates[1:])
            ax.axhline(median_rate, color="red", linestyle="--",
                       label=f"Median: {median_rate:.1f}'/min")
            ax.legend(fontsize=8)
    ax.set_xlabel("Session time (min)")
    ax.set_ylabel("Avg drift rate (arcmin/min)")
    ax.set_title("Free-Run Drift Rate\n(flat = constant bias, rising = accelerating)")
    ax.grid(True, alpha=0.3)

    out_path = Path(session_path).parent / "imu_freerun.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")

    # --- Stats ---
    print(f"\n=== IMU Free-Running Drift Analysis ===")
    print(f"Session duration: {(events[-1]['t'] - events[0]['t']) / 60:.1f} min")
    print(f"Successful solves: {len(successful)}")
    print(f"Free-run IMU samples: {len(freerun_times)}")

    if drift_arcmin:
        print(f"\nDrift from truth at plate-solve times:")
        print(f"  Final: {drift_arcmin[-1]:.1f}' (after {drift_times[-1]/60:.1f} min)")
        print(f"  Max:   {max(drift_arcmin):.1f}'")
        print(f"  Mean:  {np.mean(drift_arcmin):.1f}'")

    if corrected_drift:
        print(f"\nFor comparison, corrected-each-solve drift:")
        print(f"  Median: {np.median(corrected_drift):.1f}'")
        print(f"  P90:    {np.percentile(corrected_drift, 90):.1f}'")

    if drift_arcmin and drift_times[-1] > 60:
        rate = drift_arcmin[-1] / (drift_times[-1] / 60)
        print(f"\nOverall drift rate: {rate:.1f}'/min")
        print(f"  → At this rate, after 1 hour without correction: ~{rate * 60:.0f}'")
        print(f"  → After 5 min without correction: ~{rate * 5:.0f}'")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(Path(__file__).parent / "session_20260309.jsonl")
