"""
Truss flex analysis.

Hypothesis: when pushing the telescope, truss tubes flex, causing the IMU
(mounted on one end) to overshoot relative to the optical axis. The error
should be in the direction of the slew — the IMU "leads" the optics.

If confirmed, a simple proportional correction during movement would work:
  corrected_pos = imu_pos - k * slew_direction
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
    return np.degrees(np.arccos(np.clip(cos_sep, -1, 1))) * 60


def main(session_path):
    header, events = load_session(session_path)
    t0 = events[0]["t"]

    successful = [
        e for e in events
        if e["e"] == "solve" and e.get("ra") is not None and e.get("pred_ra") is not None
    ]

    # Build pairs of consecutive solves
    pairs = []
    for i in range(1, len(successful)):
        prev = successful[i - 1]
        curr = successful[i]
        dt = curr["t"] - prev["t"]
        if dt <= 0 or dt > 30:
            continue

        # Slew direction (where the scope actually moved)
        slew_ra = curr["ra"] - prev["ra"]
        slew_dec = curr["dec"] - prev["dec"]
        slew_mag = np.sqrt(slew_ra**2 + slew_dec**2)

        # Error vector (predicted - actual): where the IMU overshot
        err_ra = curr["pred_ra"] - curr["ra"]
        err_dec = curr["pred_dec"] - curr["dec"]
        err_mag = np.sqrt(err_ra**2 + err_dec**2)

        if slew_mag < 0.01:  # skip near-zero slews
            continue

        # Angle between error vector and slew direction
        # If flex hypothesis is correct, these should be aligned (cos ~ 1)
        dot = (slew_ra * err_ra + slew_dec * err_dec) / (slew_mag * err_mag) if err_mag > 0.001 else 0
        dot = np.clip(dot, -1, 1)
        angle = np.degrees(np.arccos(abs(dot)))  # 0 = aligned, 90 = perpendicular

        # Signed projection: positive = error in slew direction (overshoot)
        projection = (slew_ra * err_ra + slew_dec * err_dec) / slew_mag

        pairs.append({
            "dt": dt,
            "slew_ra": slew_ra,
            "slew_dec": slew_dec,
            "slew_mag": slew_mag,
            "err_ra": err_ra,
            "err_dec": err_dec,
            "err_mag": err_mag,
            "alignment_angle": angle,
            "projection": projection,  # positive = overshoot in slew dir
            "t": curr["t"] - t0,
        })

    # Split by slew size
    stationary = [p for p in pairs if p["slew_mag"] < 0.05]  # < 3 arcmin
    moving = [p for p in pairs if p["slew_mag"] >= 0.05]

    fig, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
    fig.suptitle("Truss Flex Analysis: Does IMU Overshoot in Slew Direction?", fontsize=13, fontweight="bold")

    # Panel 1: Error vs slew vectors (quiver plot)
    ax = axes[0, 0]
    for p in moving:
        # Slew vector (blue)
        scale = 1.0
        ax.annotate("", xy=(p["slew_ra"] * scale, p["slew_dec"] * scale),
                     xytext=(0, 0),
                     arrowprops=dict(arrowstyle="->", color="steelblue", alpha=0.3, lw=1))
        # Error vector (red)
        ax.annotate("", xy=(p["err_ra"] * scale * 5, p["err_dec"] * scale * 5),
                     xytext=(0, 0),
                     arrowprops=dict(arrowstyle="->", color="orangered", alpha=0.3, lw=1))
    ax.set_xlabel("RA component (deg)")
    ax.set_ylabel("Dec component (deg)")
    ax.set_title("Slew (blue) vs Error (red, 5x) Vectors\n(aligned = flex)")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.axhline(0, color="gray", alpha=0.2)
    ax.axvline(0, color="gray", alpha=0.2)

    # Panel 2: Alignment angle histogram (moving only)
    ax = axes[0, 1]
    if moving:
        angles = [p["alignment_angle"] for p in moving]
        ax.hist(angles, bins=18, range=(0, 90), color="steelblue", alpha=0.7, edgecolor="white")
        ax.axvline(np.median(angles), color="red", linestyle="--",
                   label=f"Median: {np.median(angles):.0f}°")
        ax.axvline(45, color="gray", linestyle=":", alpha=0.5, label="Random (45°)")
        ax.legend(fontsize=9)
    ax.set_xlabel("Angle between error and slew direction (deg)")
    ax.set_ylabel("Count")
    ax.set_title("Error-Slew Alignment (moving only)\n(peaked at 0° = flex confirmed)")
    ax.grid(True, alpha=0.3)

    # Panel 3: Signed projection vs slew magnitude
    ax = axes[1, 0]
    if moving:
        slew_mags = [p["slew_mag"] * 60 for p in moving]  # to arcmin
        projs = [p["projection"] * 60 for p in moving]  # to arcmin
        colors = ["orangered" if p > 0 else "steelblue" for p in projs]
        ax.scatter(slew_mags, projs, c=colors, s=20, alpha=0.6)
        ax.axhline(0, color="gray", alpha=0.3)

        # Fit line through moving data
        if len(slew_mags) > 5:
            coeffs = np.polyfit(slew_mags, projs, 1)
            fit_x = np.linspace(0, max(slew_mags), 50)
            ax.plot(fit_x, np.polyval(coeffs, fit_x), "--", color="black",
                    label=f"Slope: {coeffs[0]:.3f} (flex fraction)\nIntercept: {coeffs[1]:.1f}'")
            ax.legend(fontsize=9)

        overshoot_pct = 100 * sum(1 for p in projs if p > 0) / len(projs) if projs else 0
        ax.set_title(f"Error Projected onto Slew Direction\n(+ve = overshoot, {overshoot_pct:.0f}% positive)")
    ax.set_xlabel("Slew magnitude (arcmin)")
    ax.set_ylabel("Projected error (arcmin, +ve = overshoot)")
    ax.grid(True, alpha=0.3)

    # Panel 4: What correction factor would minimize error?
    ax = axes[1, 1]
    if moving:
        # For each moving solve, what fraction of the slew is the overshoot?
        fractions = [p["projection"] / p["slew_mag"] for p in moving if p["slew_mag"] > 0.02]
        if fractions:
            ax.hist(fractions, bins=30, color="teal", alpha=0.7, edgecolor="white")
            median_frac = np.median(fractions)
            ax.axvline(median_frac, color="red", linestyle="--",
                       label=f"Median: {median_frac:.3f}")
            mean_frac = np.mean([f for f in fractions if abs(f) < 1])  # trim outliers
            ax.axvline(mean_frac, color="orange", linestyle=":",
                       label=f"Trimmed mean: {mean_frac:.3f}")
            ax.legend(fontsize=9)
    ax.set_xlabel("Overshoot as fraction of slew")
    ax.set_ylabel("Count")
    ax.set_title("Flex Correction Factor\n(consistent value = modelable)")
    ax.grid(True, alpha=0.3)

    out_path = Path(session_path).parent / "flex_analysis.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")

    # Stats
    if moving:
        angles = [p["alignment_angle"] for p in moving]
        projs = [p["projection"] * 60 for p in moving]
        fractions = [p["projection"] / p["slew_mag"] for p in moving if p["slew_mag"] > 0.02]
        overshoot_count = sum(1 for p in projs if p > 0)

        print(f"\n=== Flex Analysis ({len(moving)} moving solves) ===")
        print(f"Error-slew alignment: median {np.median(angles):.0f}° (0° = perfect flex, 45° = random)")
        print(f"Overshoot direction: {overshoot_count}/{len(projs)} positive ({100*overshoot_count/len(projs):.0f}%)")
        print(f"Projection: median {np.median(projs):.1f}', mean {np.mean(projs):.1f}'")
        if fractions:
            print(f"Flex fraction: median {np.median(fractions):.4f}, trimmed mean {np.mean([f for f in fractions if abs(f) < 1]):.4f}")

        if np.median(angles) < 30 and overshoot_count / len(projs) > 0.6:
            print("\n→ FLEX CONFIRMED: errors are aligned with slew direction and consistently overshoot.")
            print(f"→ A correction of ~{abs(np.median(fractions))*100:.1f}% of slew magnitude would reduce mid-slew error.")
        elif np.median(angles) < 45:
            print("\n→ PARTIAL: some alignment but noisy. More data needed.")
        else:
            print("\n→ NOT CONFIRMED: errors appear random relative to slew direction.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main(Path(__file__).parent / "session_20260309.jsonl")
