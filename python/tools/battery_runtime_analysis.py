#!/usr/bin/env python3
"""
Analyze battery runtime-test telemetry into a proposed SOC_LUT.

Consumes run directories produced by the battery-runtime-test branch
(``~/PiFinder_data/battery_runtime/run_<serial>_<stamp>/``), each holding
``telemetry.csv`` + ``run_metadata.json``. Methodology per
docs/adr/0020-soc-as-runtime-fraction.md: state of charge is the
fraction of typical-load runtime remaining, so within each run's
discharge segment SoC(t) = (T_cutoff - t) / (T_cutoff - T_unplug).

Usage:
    python tools/battery_runtime_analysis.py RUN_DIR [RUN_DIR ...]
    python tools/battery_runtime_analysis.py --scan PARENT_DIR [--plot]

Lessons from the first (2026-07-17) campaign baked in here:

* **ADC-blind tail.** Below ~3.50 V the BQ25895 one-shot ADC stops
  completing and BATV reads raw 0 (decoded as the 2.304 V offset) while
  the system keeps running — on both first-campaign devices for the
  final ~8-11% of runtime. Rows with battery_voltage <= SANE_VOLTAGE_MIN
  are excluded from the curve, but the run's cutoff time is still the
  last row of the file (power really died then). The curve therefore
  bottoms out at the last sane sample; knot percents below that are
  extrapolated and flagged.
* **Load verdicts.** ``solve_attempt_age_s`` alone cannot prove the
  pinned load: the first campaign attempted solves all night but the
  frames were blanked (IMU pseudo-motion), so attempts churned at full
  rate with zero matches. A run is *pinned* only if camera solving
  (matches > 0) ran for >=90% of the discharge; *degraded* (attempts
  churning, no solves — capture/display/CPU load close to pinned but
  not identical) if attempts stayed live; *dead* (excluded) if attempts
  stopped. Degraded runs are included in the fit with a warning.

Stdlib-only; ``--plot`` uses matplotlib if installed.
"""

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

# SoC grid for the proposed knots. Denser near the ends, where the
# Li-ion curve bends and the UI most needs accuracy.
KNOT_PERCENTS = [0, 5, 10, 15, 25, 50, 75, 90, 100]

# Rows at or below this are ADC-blind reads (BATV raw 0 decodes to
# 2.304 V), not real cell voltages.
SANE_VOLTAGE_MIN = 2.35

# Solve attempts older than this mean the capture/solve chain died.
SOLVE_LIVENESS_LIMIT_S = 120.0

# Fraction of discharge rows that must show actual camera solves
# (matches > 0) for the run to count as the pinned load.
PINNED_SOLVE_FRACTION = 0.90

# Voltage averaging half-window (in SoC %) for the knot fit — smooths
# the 20 mV ADC quantisation instead of interpolating between two
# arbitrary samples.
SMOOTH_HALF_WINDOW_PCT = 1.5


def load_run(run_dir: Path):
    """Read one run dir -> dict with metadata and discharge-segment rows."""
    with open(run_dir / "run_metadata.json") as f:
        metadata = json.load(f)
    with open(run_dir / "telemetry.csv") as f:
        rows = [r for r in csv.DictReader(f) if r.get("battery_voltage_v")]
    if not rows:
        raise ValueError(f"{run_dir}: no telemetry rows")

    # Discharge clock starts at the cable pull (on_external_power 1 -> 0),
    # or at the first row if the run never saw external power.
    start_idx = 0
    for i in range(1, len(rows)):
        if rows[i - 1]["on_external_power"] == "1" and (
            rows[i]["on_external_power"] == "0"
        ):
            start_idx = i
    discharge = [r for r in rows[start_idx:] if r["on_external_power"] == "0"]
    if len(discharge) < 10:
        raise ValueError(f"{run_dir}: discharge segment too short to analyze")

    return {"dir": run_dir, "metadata": metadata, "rows": discharge}


def run_report(run) -> dict:
    rows = run["rows"]
    t = [float(r["monotonic_s"]) for r in rows]
    duration_s = t[-1] - t[0]

    sane = [(ti, float(r["battery_voltage_v"])) for ti, r in zip(t, rows)
            if float(r["battery_voltage_v"]) > SANE_VOLTAGE_MIN]
    blind_tail_s = t[-1] - sane[-1][0] if sane else duration_s

    ages = [float(r["solve_attempt_age_s"]) for r in rows if r["solve_attempt_age_s"]]
    attempts_live = bool(ages) and max(ages) <= SOLVE_LIVENESS_LIMIT_S
    solving_rows = sum(
        1 for r in rows if r["solve_matches"] not in ("", "None", "0")
    )
    solve_fraction = solving_rows / len(rows)
    if not attempts_live:
        load_verdict = "dead"
    elif solve_fraction >= PINNED_SOLVE_FRACTION:
        load_verdict = "pinned"
    else:
        load_verdict = "degraded"

    temps = [float(r["cpu_temp_c"]) for r in rows if r["cpu_temp_c"]]
    throttled = {r["throttled_hex"] for r in rows if r["throttled_hex"]} - {"0"}

    return {
        "serial": run["metadata"].get("serial", "?"),
        "dir": run["dir"].name,
        "duration_s": duration_s,
        "unplug_voltage": sane[0][1] if sane else None,
        "last_sane_voltage": sane[-1][1] if sane else None,
        "blind_tail_s": blind_tail_s,
        "samples": len(rows),
        "sane_samples": len(sane),
        "load_verdict": load_verdict,
        "solve_fraction": solve_fraction,
        "max_cpu_temp_c": max(temps) if temps else None,
        "throttled": sorted(throttled),
    }


def run_soc_series(run):
    """[(soc_pct, voltage), ...] for one run's sane discharge samples.

    The SoC denominator uses the FULL discharge (through the ADC-blind
    tail to actual power death); only the voltage pairing is limited to
    sane samples.
    """
    rows = run["rows"]
    t = [float(r["monotonic_s"]) for r in rows]
    t0, t_end = t[0], t[-1]
    span = t_end - t0
    return [
        ((t_end - ti) / span * 100.0, float(r["battery_voltage_v"]))
        for ti, r in zip(t, rows)
        if float(r["battery_voltage_v"]) > SANE_VOLTAGE_MIN
    ]


def voltage_at_percent(series, pct: float):
    """Windowed-mean voltage of one run at a given SoC percent; None when
    the percent is below the run's measured (sane) range."""
    lo = min(s for s, _ in series)
    if pct < lo - SMOOTH_HALF_WINDOW_PCT:
        return None
    window = [v for s, v in series if abs(s - pct) <= SMOOTH_HALF_WINDOW_PCT]
    if window:
        return statistics.mean(window)
    # Sparse region: linear interpolation between neighbours.
    below = [(s, v) for s, v in series if s <= pct]
    above = [(s, v) for s, v in series if s >= pct]
    if not below or not above:
        return None
    s_lo, v_lo = max(below)
    s_hi, v_hi = min(above, key=lambda p: p[0])
    if s_hi == s_lo:
        return (v_lo + v_hi) / 2
    return v_lo + (pct - s_lo) / (s_hi - s_lo) * (v_hi - v_lo)


def propose_lut(runs):
    """Mean-across-runs voltage at each knot percent.

    Returns (knots, extrapolated_percents). Knot percents below every
    run's measured range are extrapolated by extending the slope of the
    two lowest measured knots, and flagged.
    """
    all_series = [run_soc_series(r) for r in runs]
    measured = []
    extrapolated = []
    for pct in KNOT_PERCENTS:
        voltages = []
        for s in all_series:
            v = voltage_at_percent(s, pct)
            if v is not None:
                voltages.append(v)
        if voltages:
            measured.append((pct, statistics.mean(voltages)))
        else:
            extrapolated.append(pct)

    measured.sort()
    knots = {pct: v for pct, v in measured}
    if extrapolated and len(measured) >= 2:
        (p0, v0), (p1, v1) = measured[0], measured[1]
        slope = (v1 - v0) / (p1 - p0)
        for pct in extrapolated:
            knots[pct] = v0 + slope * (pct - p0)

    lut = sorted((round(v, 3), pct) for pct, v in knots.items())
    return lut, set(extrapolated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="*", type=Path)
    parser.add_argument("--scan", type=Path, help="parent dir; analyze every run_* inside")
    parser.add_argument("--plot", action="store_true", help="scatter + knots (needs matplotlib)")
    args = parser.parse_args()

    dirs = list(args.run_dirs)
    if args.scan:
        dirs += sorted(args.scan.glob("run_*"))
    if not dirs:
        parser.error("no run dirs given (positional or --scan)")

    runs = []
    degraded_used = False
    for d in dirs:
        try:
            run = load_run(d)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"SKIP {d}: {e}", file=sys.stderr)
            continue
        rep = run_report(run)
        h, m = divmod(int(rep["duration_s"] // 60), 60)
        print(
            f"{rep['dir']} (serial {rep['serial']}): {h}h{m:02d}m, "
            f"{rep['unplug_voltage']:.3f} V -> {rep['last_sane_voltage']:.3f} V sane "
            f"(+{rep['blind_tail_s']/60:.0f} min ADC-blind tail to power death), "
            f"{rep['sane_samples']}/{rep['samples']} sane samples, "
            f"load: {rep['load_verdict'].upper()} "
            f"(solving {rep['solve_fraction']*100:.0f}% of rows), "
            f"max CPU {rep['max_cpu_temp_c']} C"
            + (f", THROTTLED {rep['throttled']}" if rep["throttled"] else "")
        )
        if rep["load_verdict"] == "dead":
            print("  -> excluded: solve attempts stopped mid-run", file=sys.stderr)
            continue
        if rep["load_verdict"] == "degraded":
            degraded_used = True
        runs.append(run)

    if not runs:
        print("\nNo usable runs — nothing to fit.", file=sys.stderr)
        sys.exit(1)

    lut, extrapolated = propose_lut(runs)
    print(f"\nProposed SOC_LUT from {len(runs)} run(s)")
    if degraded_used:
        print("# WARNING: includes DEGRADED-load run(s) — camera solving was not")
        print("# active for the whole discharge; treat as provisional and confirm")
        print("# with a pinned-load run before shipping.")
    print("# Piecewise-linear state-of-charge curve: (battery_voltage_V, percent).")
    print("# Measured: remaining-runtime fraction under the pinned typical load")
    print("# (docs/adr/0020-soc-as-runtime-fraction.md).")
    print("SOC_LUT = [")
    for v, pct in lut:
        tag = "  # extrapolated (below ADC-blind floor)" if pct in extrapolated else ""
        print(f"    ({v:.3f}, {pct}),{tag}")
    print("]")

    if args.plot:
        import matplotlib.pyplot as plt

        for run in runs:
            series = run_soc_series(run)
            plt.plot([v for _, v in series], [s for s, _ in series],
                     ".", markersize=2, alpha=0.4,
                     label=run["metadata"].get("serial", "?"))
        plt.plot([v for v, _ in lut], [p for _, p in lut], "k.-", label="knots")
        plt.xlabel("battery voltage (V)")
        plt.ylabel("SoC = remaining-runtime fraction (%)")
        plt.legend()
        plt.show()


if __name__ == "__main__":
    main()
