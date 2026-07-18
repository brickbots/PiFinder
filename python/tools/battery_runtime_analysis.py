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

Per run it reports runtime, unplug/cutoff voltages and load-liveness
checks; across runs it pools the (SoC, voltage) samples and prints a
proposed ``SOC_LUT`` snippet for battery_bq25895.py.

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
KNOT_PERCENTS = [0, 5, 10, 25, 50, 75, 90, 100]

# A healthy pinned load solves continuously; if the newest solve attempt
# is ever older than this within the discharge, the capture/solve chain
# died and the run's load (and thus its curve) is suspect.
SOLVE_LIVENESS_LIMIT_S = 120.0


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
    v = [float(r["battery_voltage_v"]) for r in rows]
    duration_s = t[-1] - t[0]

    solve_ages = [float(r["solve_attempt_age_s"]) for r in rows if r["solve_attempt_age_s"]]
    max_solve_age = max(solve_ages) if solve_ages else None
    load_ok = max_solve_age is not None and max_solve_age <= SOLVE_LIVENESS_LIMIT_S
    charging_rows = sum(1 for r in rows if r["charge_status"] not in ("NOT_CHARGING",))

    temps = [float(r["cpu_temp_c"]) for r in rows if r["cpu_temp_c"]]

    return {
        "serial": run["metadata"].get("serial", "?"),
        "dir": run["dir"].name,
        "duration_s": duration_s,
        "unplug_voltage": v[0],
        "cutoff_voltage": v[-1],
        "samples": len(rows),
        "max_solve_age_s": max_solve_age,
        "load_ok": load_ok,
        "charging_rows": charging_rows,
        "max_cpu_temp_c": max(temps) if temps else None,
    }


def run_soc_series(run):
    """[(soc_pct, voltage), ...] for one run's discharge segment."""
    rows = run["rows"]
    t = [float(r["monotonic_s"]) for r in rows]
    v = [float(r["battery_voltage_v"]) for r in rows]
    t0, t_end = t[0], t[-1]
    span = t_end - t0
    return [((t_end - ti) / span * 100.0, vi) for ti, vi in zip(t, v)]


def voltage_at_percent(series, pct: float) -> float:
    """Interpolate one run's voltage at a given SoC percent. The series is
    ordered by time (SoC descending)."""
    below = [(s, v) for s, v in series if s <= pct]
    above = [(s, v) for s, v in series if s >= pct]
    if not below:
        return series[-1][1]
    if not above:
        return series[0][1]
    s_lo, v_lo = max(below, key=lambda p: p[0])
    s_hi, v_hi = min(above, key=lambda p: p[0])
    if s_hi == s_lo:
        return (v_lo + v_hi) / 2
    frac = (pct - s_lo) / (s_hi - s_lo)
    return v_lo + frac * (v_hi - v_lo)


def propose_lut(runs):
    """Median-across-runs voltage at each knot percent -> [(V, pct), ...]."""
    all_series = [run_soc_series(r) for r in runs]
    knots = []
    for pct in KNOT_PERCENTS:
        voltages = [voltage_at_percent(s, pct) for s in all_series]
        knots.append((round(statistics.median(voltages), 3), pct))
    knots.sort()
    return knots


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

    runs, poisoned = [], []
    for d in dirs:
        try:
            run = load_run(d)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"SKIP {d}: {e}", file=sys.stderr)
            continue
        report = run_report(run)
        h, m = divmod(int(report["duration_s"] // 60), 60)
        flags = []
        if not report["load_ok"]:
            flags.append("LOAD DIED / no solver liveness — excluded from fit")
        if report["charging_rows"]:
            flags.append(f"{report['charging_rows']} charging rows inside discharge")
        print(
            f"{report['dir']} (serial {report['serial']}): {h}h{m:02d}m, "
            f"{report['unplug_voltage']:.3f} V → {report['cutoff_voltage']:.3f} V, "
            f"{report['samples']} samples, max solve age "
            f"{report['max_solve_age_s']}, max CPU {report['max_cpu_temp_c']} °C"
            + ("".join(f"  [{f}]" for f in flags))
        )
        (runs if report["load_ok"] else poisoned).append(run)

    if not runs:
        print("\nNo clean runs — nothing to fit.", file=sys.stderr)
        sys.exit(1)

    knots = propose_lut(runs)
    print(f"\nProposed SOC_LUT from {len(runs)} clean run(s)")
    print("# Piecewise-linear state-of-charge curve: (battery_voltage_V, percent).")
    print("# Measured: remaining-runtime fraction under the pinned typical load")
    print("# (docs/adr/0020-soc-as-runtime-fraction.md).")
    print("SOC_LUT = [")
    for v, pct in knots:
        print(f"    ({v:.3f}, {pct}),")
    print("]")

    if args.plot:
        import matplotlib.pyplot as plt

        for run in runs:
            series = run_soc_series(run)
            plt.plot([v for _, v in series], [s for s, _ in series],
                     ".", markersize=2, alpha=0.4,
                     label=run["metadata"].get("serial", "?"))
        plt.plot([v for v, _ in knots], [p for _, p in knots], "k.-", label="knots")
        plt.xlabel("battery voltage (V)")
        plt.ylabel("SoC = remaining-runtime fraction (%)")
        plt.legend()
        plt.show()


if __name__ == "__main__":
    main()
