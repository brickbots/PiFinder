"""
Analyze IMU drift characteristics to determine if a Kalman filter would help.

Key questions:
1. How does drift grow with time since last solve? (linear = bias, sqrt = random walk)
2. How does drift correlate with slew magnitude?
3. Is there a systematic bias direction?
4. What's the error structure — does it look filterable?
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timezone, timedelta


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
    ra1, dec1, ra2, dec2 = map(np.radians, [ra1, dec1, ra2, dec2])
    cos_sep = np.sin(dec1) * np.sin(dec2) + np.cos(dec1) * np.cos(dec2) * np.cos(
        ra1 - ra2
    )
    return np.degrees(np.arccos(np.clip(cos_sep, -1, 1))) * 60  # arcmin


def quat_angular_diff(q1, q2):
    """Angular difference between two quaternions [w,x,y,z] in degrees."""
    q1 = np.array(q1) / np.linalg.norm(q1)
    q2 = np.array(q2) / np.linalg.norm(q2)
    dot = abs(np.dot(q1, q2))
    dot = min(dot, 1.0)
    return np.degrees(2 * np.arccos(dot))


def main(session_path):
    header, events = load_session(session_path)
    t0 = events[0]["t"]

    solves = [e for e in events if e["e"] == "solve"]
    imus = [e for e in events if e["e"] == "imu"]
    successful = [s for s in solves if s.get("ra") is not None]
    with_pred = [s for s in successful if s.get("pred_ra") is not None]

    # --- Build solve pairs: consecutive successful solves ---
    # For each solve with prediction, compute:
    # - time since previous successful solve
    # - IMU quaternion change since previous solve
    # - prediction error (drift)
    # - slew magnitude (how far the scope actually moved)

    solve_pairs = []
    for i in range(1, len(with_pred)):
        prev = with_pred[i - 1]
        curr = with_pred[i]

        dt = curr["t"] - prev["t"]
        if dt <= 0 or dt > 30:  # skip gaps > 30s
            continue

        drift = angular_separation(
            curr["ra"], curr["dec"], curr["pred_ra"], curr["pred_dec"]
        )
        slew = angular_separation(
            curr["ra"], curr["dec"], prev["ra"], prev["dec"]
        )

        # Signed errors in RA and Dec (for bias detection)
        ra_err = curr["pred_ra"] - curr["ra"]  # positive = predicted too far east
        dec_err = curr["pred_dec"] - curr["dec"]

        # IMU quaternion change
        quat_change = None
        if prev.get("iq") and curr.get("iq"):
            quat_change = quat_angular_diff(prev["iq"], curr["iq"])

        solve_pairs.append({
            "dt": dt,
            "drift": drift,
            "slew": slew,
            "ra_err": ra_err,
            "dec_err": dec_err,
            "quat_change": quat_change,
            "t": curr["t"] - t0,
        })

    # --- Also look at IMU rate during slews vs stationary ---
    imu_ts = np.array([i["t"] for i in imus])
    imu_moving = np.array([i.get("mv", False) for i in imus])

    # --- Plot ---
    fig, axes = plt.subplots(3, 2, figsize=(14, 14), constrained_layout=True)
    fig.suptitle("IMU Drift Analysis: Is a Kalman Filter the Right Tool?", fontsize=13, fontweight="bold")

    dts = [p["dt"] for p in solve_pairs]
    drifts = [p["drift"] for p in solve_pairs]
    slews = [p["slew"] for p in solve_pairs]
    ra_errs = [p["ra_err"] for p in solve_pairs]
    dec_errs = [p["dec_err"] for p in solve_pairs]
    quat_changes = [p["quat_change"] for p in solve_pairs if p["quat_change"] is not None]
    quat_drifts = [p["drift"] for p in solve_pairs if p["quat_change"] is not None]
    quat_slews = [p["slew"] for p in solve_pairs if p["quat_change"] is not None]

    # Panel 1: Drift vs time since last solve
    ax = axes[0, 0]
    ax.scatter(dts, drifts, c="orangered", s=15, alpha=0.7)
    # Fit: does drift grow linearly (bias) or sqrt (random walk)?
    dt_arr = np.array(dts)
    drift_arr = np.array(drifts)
    mask = dt_arr > 0.5  # ignore very short intervals
    if mask.sum() > 5:
        # Linear fit
        coeffs_lin = np.polyfit(dt_arr[mask], drift_arr[mask], 1)
        dt_fit = np.linspace(dt_arr[mask].min(), dt_arr[mask].max(), 50)
        ax.plot(dt_fit, np.polyval(coeffs_lin, dt_fit), "--", color="blue",
                label=f"Linear: {coeffs_lin[0]:.1f}'/s + {coeffs_lin[1]:.1f}'")
        # Sqrt fit
        coeffs_sqrt = np.polyfit(np.sqrt(dt_arr[mask]), drift_arr[mask], 1)
        ax.plot(dt_fit, np.polyval(coeffs_sqrt, np.sqrt(dt_fit)), ":", color="green",
                label=f"Sqrt: {coeffs_sqrt[0]:.1f}'/sqrt(s)")
        ax.legend(fontsize=8)
    ax.set_xlabel("Time since last solve (s)")
    ax.set_ylabel("Drift (arcmin)")
    ax.set_title("Drift vs Time Gap\n(linear = bias, sqrt = random walk)")
    ax.grid(True, alpha=0.3)

    # Panel 2: Drift vs slew magnitude
    ax = axes[0, 1]
    ax.scatter(slews, drifts, c="steelblue", s=15, alpha=0.7)
    if len(slews) > 5:
        coeffs = np.polyfit(slews, drifts, 1)
        slew_fit = np.linspace(0, max(slews), 50)
        ax.plot(slew_fit, np.polyval(coeffs, slew_fit), "--", color="red",
                label=f"Slope: {coeffs[0]:.2f} (drift per arcmin slew)")
        ax.legend(fontsize=8)
    ax.set_xlabel("Slew magnitude (arcmin)")
    ax.set_ylabel("Drift (arcmin)")
    ax.set_title("Drift vs Slew Size\n(strong correlation → geometric/alignment issue)")
    ax.grid(True, alpha=0.3)

    # Panel 3: Signed RA/Dec errors — bias detection
    ax = axes[1, 0]
    ax.scatter(ra_errs, dec_errs, c="purple", s=15, alpha=0.5)
    ax.axhline(0, color="gray", alpha=0.3)
    ax.axvline(0, color="gray", alpha=0.3)
    mean_ra = np.mean(ra_errs)
    mean_dec = np.mean(dec_errs)
    ax.plot(mean_ra, mean_dec, "r*", markersize=15, label=f"Mean: ({mean_ra:.2f}, {mean_dec:.2f}) deg")
    # Draw 1-sigma ellipse
    from matplotlib.patches import Ellipse
    std_ra = np.std(ra_errs)
    std_dec = np.std(dec_errs)
    ell = Ellipse((mean_ra, mean_dec), 2*std_ra, 2*std_dec, fill=False, color="red", linestyle="--", alpha=0.5)
    ax.add_patch(ell)
    ax.set_xlabel("RA error (pred - actual, deg)")
    ax.set_ylabel("Dec error (pred - actual, deg)")
    ax.set_title("Error Direction & Bias\n(centered = no bias, offset = systematic)")
    ax.legend(fontsize=8)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # Panel 4: Drift vs quaternion change
    ax = axes[1, 1]
    if quat_changes:
        ax.scatter(quat_changes, quat_drifts, c="teal", s=15, alpha=0.7)
        if len(quat_changes) > 5:
            coeffs = np.polyfit(quat_changes, quat_drifts, 1)
            q_fit = np.linspace(0, max(quat_changes), 50)
            ax.plot(q_fit, np.polyval(coeffs, q_fit), "--", color="red",
                    label=f"Slope: {coeffs[0]:.2f}")
            ax.legend(fontsize=8)
    ax.set_xlabel("IMU quaternion change (deg)")
    ax.set_ylabel("Drift (arcmin)")
    ax.set_title("Drift vs IMU Rotation\n(proportional → quat-to-radec mapping error)")
    ax.grid(True, alpha=0.3)

    # Panel 5: Error over session time (is there a trend?)
    ax = axes[2, 0]
    times_min = [p["t"] / 60 for p in solve_pairs]
    ax.scatter(times_min, drifts, c="orangered", s=15, alpha=0.7)
    # Sliding median
    if len(times_min) > 10:
        window = 10
        t_med = [np.mean(times_min[i:i+window]) for i in range(len(times_min) - window)]
        d_med = [np.median(drifts[i:i+window]) for i in range(len(drifts) - window)]
        ax.plot(t_med, d_med, "-", color="blue", linewidth=2, alpha=0.7, label="Sliding median (10)")
        ax.legend(fontsize=8)
    ax.set_xlabel("Session time (min)")
    ax.set_ylabel("Drift (arcmin)")
    ax.set_title("Drift Over Session\n(trend = thermal/calibration drift)")
    ax.grid(True, alpha=0.3)

    # Panel 6: Histogram of drift — what distribution?
    ax = axes[2, 1]
    ax.hist(drifts, bins=30, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(np.median(drifts), color="red", linestyle="--", label=f"Median: {np.median(drifts):.1f}'")
    ax.axvline(np.percentile(drifts, 90), color="orange", linestyle=":", label=f"P90: {np.percentile(drifts, 90):.1f}'")
    ax.set_xlabel("Drift (arcmin)")
    ax.set_ylabel("Count")
    ax.set_title("Drift Distribution\n(heavy tail → outlier problem, not filter problem)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    out_path = Path(session_path).parent / "drift_analysis.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")

    # --- Print analysis ---
    print("\n=== Drift Analysis ===")
    print(f"Solve pairs analyzed: {len(solve_pairs)}")
    print(f"Drift: median {np.median(drifts):.1f}', mean {np.mean(drifts):.1f}', P90 {np.percentile(drifts, 90):.1f}'")
    print(f"Mean signed error: RA {mean_ra:.3f} deg, Dec {mean_dec:.3f} deg")
    print(f"  → {'Significant RA bias' if abs(mean_ra) > 0.05 else 'No significant RA bias'}")
    print(f"  → {'Significant Dec bias' if abs(mean_dec) > 0.05 else 'No significant Dec bias'}")

    # Correlation analysis
    corr_dt = np.corrcoef(dts, drifts)[0, 1]
    corr_slew = np.corrcoef(slews, drifts)[0, 1]
    print(f"\nCorrelations with drift:")
    print(f"  Time gap:  r = {corr_dt:.3f}  {'(strong)' if abs(corr_dt) > 0.5 else '(weak)'}")
    print(f"  Slew size: r = {corr_slew:.3f}  {'(strong)' if abs(corr_slew) > 0.5 else '(weak)'}")
    if quat_changes:
        corr_quat = np.corrcoef(quat_changes, quat_drifts)[0, 1]
        print(f"  Quat change: r = {corr_quat:.3f}  {'(strong)' if abs(corr_quat) > 0.5 else '(weak)'}")

    # Stationary vs moving drift
    stationary = [p for p in solve_pairs if p["slew"] < 5]  # < 5 arcmin
    moving = [p for p in solve_pairs if p["slew"] >= 5]
    if stationary:
        print(f"\nStationary (slew < 5'): median drift {np.median([p['drift'] for p in stationary]):.1f}', n={len(stationary)}")
    if moving:
        print(f"Moving (slew >= 5'):    median drift {np.median([p['drift'] for p in moving]):.1f}', n={len(moving)}")

    print("\n=== Verdict ===")
    if corr_slew > 0.7:
        print("Drift is strongly correlated with slew magnitude.")
        print("This suggests a geometric/alignment issue in the quat→RA/Dec mapping,")
        print("not IMU noise. A Kalman filter won't fix a systematic mapping error.")
        print("→ Investigate the dead-reckoning coordinate transform.")
    elif corr_dt > 0.7:
        print("Drift grows strongly with time — consistent with IMU bias.")
        print("A Kalman filter COULD help by estimating and compensating the bias.")
        print("→ Consider an EKF with bias state.")
    elif abs(mean_ra) > 0.1 or abs(mean_dec) > 0.1:
        print("Systematic bias detected in prediction errors.")
        print("A simple bias correction might be more effective than a full KF.")
    else:
        print("Drift appears to be dominated by large outliers during slews,")
        print("with low stationary drift. A Kalman filter would help marginally")
        print("at best — the real issue is that solves fail during slews,")
        print("leaving the IMU to dead-reckon over large rotations.")
        print("→ Better fix: faster solve cadence or shorter exposure during slews.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(Path(__file__).parent / "session_20260309.jsonl")
