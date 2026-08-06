# State of charge means remaining-runtime fraction under typical load

The state-of-charge percentage shown in the UI is defined as the **expected fraction of typical-load runtime remaining**, and its voltage→percent lookup (`SOC_LUT` in `battery_bq25895.py`) is to be derived from **measured bench discharge runs** of real PiFinder rev-4 units — not from a textbook Li-ion capacity curve.

Status: **complete.** The bench campaign ran to conclusion over 2026-07-17 → 07-26: six discharges on two rev4 units, two of them under the pinned load. The shipped `SOC_LUT` is measured with no knot extrapolated and no folklore left. The campaign's own pinned-load refit was derived and then **deliberately not adopted**, because it fires the low-battery advisories roughly twice as early as intended — see *Measured outcome* below, which is the part of this ADR worth reading. **Amended by [ADR 0021](0021-blind-floor-shutdown.md):** the 0% anchor is the ADC blind floor / software-shutdown point, not the hardware cutoff voltage (which turned out to be unmeasurable — it lies below the floor).

## Context

The BQ25895 has no fuel gauge. Its ADC measures battery terminal voltage and **charge** current only — there is no discharge-current measurement and no coulomb counter, so "fraction of capacity remaining" is not observable on this hardware, at any effort level. What a bench run *can* observe, exactly, is **time**: run a fully charged unit under a fixed workload until the hardware dies, log voltage the whole way, and every sample is a known distance-in-time from cutoff.

The workload is pinned (the **typical load**: continuous capture-and-solve, screen on, display sleep off) because terminal voltage under load is what the chip reads in the field; a curve measured at a different load would systematically mis-map voltage to runtime.

## Decision

- **Semantics:** SoC(v) = expected fraction of remaining runtime under the typical load. 100% is the under-load voltage immediately after unplugging a full unit (not the 4.2 V charge-termination voltage, which a loaded cell never reads); 0% is the **low-battery shutdown at the ADC blind floor** (per [ADR 0021](0021-blind-floor-shutdown.md), which amended this — the original 0% was the hardware cutoff voltage, and the campaign established that it is not measurable, lying below the floor where no sample exists).
- **Derivation:** for each bench run, assign each telemetry sample SoC(t) = (T_cutoff − t) / (T_cutoff − T_unplug), pair it with the sampled voltage, pool the samples across runs and devices, and fit piecewise-linear knots on that scatter → new `SOC_LUT`.
- **Reproducibility:** the analysis tool and the derived knots merge together (the imu2cam-tool precedent), so the curve can be re-derived when hardware or workload changes. The raw telemetry CSVs are retained outside the repo — the campaign's six runs live in `~/battery_runtime/` on the maintainer's machine, one directory per run with `telemetry.csv` + `run_metadata.json`, which is the input format `battery_runtime_analysis.py` consumes. The bench harness lives on the never-merged `battery-runtime-test` branch on origin, whose root `BATTERY_RUNTIME_TEST.md` is the operational runbook (deploy, run, collect, analyze).

## Measured outcome (campaign complete, 2026-07-26)

Six discharge runs on **two rev4 units** (`10000000e63d1a2e` / `pifinder-dev`, `10000000777f86f4` / `pf4-dev`), across three sittings, all on software 2.6.0 with the identical pinned profile (400 ms exposure, gain 20, brightness 255, display sleep forced off):

| Sitting | Unit | Runtime | Load verdict |
|---|---|---|---|
| 2026-07-17 | e63d1a2e | 9h18m | degraded — 0% solving |
| 2026-07-17 | 777f86f4 | 8h57m | degraded — 0% solving |
| 2026-07-24 | e63d1a2e | 9h45m | degraded — 0% solving |
| 2026-07-24 | 777f86f4 | 9h10m | degraded — 0% solving |
| **2026-07-25** | **e63d1a2e** | **9h55m** | **pinned — solving 100% of rows** |
| **2026-07-26** | **777f86f4** | **10h03m** | **pinned — solving 100% of rows** |

**The first four runs never carried the load this ADR pins.** Two independent faults suppressed plate solving while leaving solve *attempts* churning at full rate, so attempt-rate alone could not detect it: BNO055 pseudo-motion blanked the substituted frame (magnetic disturbance on the bench), and systemd-logind's `RemoveIPC=yes` deleted the cedar-detect shared-memory segment at SSH logout, killing solving for the remainder of the run (fixed in #548). Both are fixed; the load verdict in `battery_runtime_analysis.py` now requires `matches > 0` for ≥90% of the discharge precisely so this failure cannot pass silently again.

**Headline runtime: about 10 hours** on a full charge under a continuously solving load with the screen at full brightness and sleep disabled. Real observing use is lighter than the pinned profile, so this is a conservative floor rather than a typical figure.

### The refit was derived, and deliberately not adopted

Fitting the two pinned runs alone (the methodologically clean input — pooling the degraded runs would violate this ADR's own premise, and the tool warns when asked) yields:

| SoC % | 0 | 5 | 10 | 15 | 25 | 50 | 75 | 90 | 100 |
|---|---|---|---|---|---|---|---|---|---|
| refit V | 3.545 | 3.611 | 3.664 | 3.700 | 3.755 | 3.841 | 3.945 | 3.973 | 4.045 |
| shipped V | 3.541 | 3.594 | 3.643 | 3.681 | 3.736 | 3.834 | 3.947 | 3.983 | 4.060 |

**The shipped curve stays.** The refit is the better fit to the voltage/runtime scatter and the *worse* setting for the only thing these knots drive in the field — when the low-battery advisories fire. The warner triggers on the first noise **dip** past a threshold, and near the flat knee one ADC LSB (20 mV) spans roughly three SoC points, so lifting the low knots ~20 mV moves the crossing much earlier in wall-clock time. Replaying both pinned runs through `LowBatteryWarner`:

| Curve | 5% warning fires before shutdown | 10% warning |
|---|---|---|
| shipped | **31 min / 38 min** | 79 min / 105 min |
| pinned-only refit | 50 min / 69 min | 86 min / 105 min |

The design intent is ~30 minutes at 5%. The shipped curve's lower knee accidentally compensates for BATV quantisation noise and hits it; the refit overshoots by a factor of two. Choosing the worse-fitting curve is the right call because the percentage is **UI advisory output, not a measurement** — it exists to time a warning, and a curve is only better if the warning lands better.

**Consequence for future work:** do not "correct" `SOC_LUT` toward a raw fit on curve-distance grounds. A candidate curve must be judged by replaying real discharge telemetry through the warner and comparing lead times. Knot distance alone is not evidence.

## Considered options

- **Remaining-runtime fraction (chosen).** Directly measurable from a discharge run; anchors 0% and 100% to real events on real hardware; answers the question users actually ask of a battery indicator ("how much longer?").
- **Generic Li-ion capacity curve, knots nudged by observation.** Keeps textbook semantics but the middle knots stay unmeasurable folklore — nothing on this board can validate "50% of capacity". Rejected as claiming precision we cannot check.
- **Coulomb counting in software.** Impossible: no discharge-current measurement exists on the BQ25895.
- **Add a fuel-gauge part.** A hardware change, out of scope for a software estimate; would obsolete this ADR if it ever happened.

## Consequences

- **The percentage is a statement about the typical load.** Lighter use (display asleep between looks, shorter exposures) drains slower *and* reads a higher voltage at equal runtime-fraction, so the estimate is conservative there; sustained heavier-than-typical use would make it optimistic. Acceptable for a UI-only estimate (see [ADR 0006](0006-battery-read-only-telemetry.md) lineage — it is never a control input).
- **No rest-voltage correction is needed or wanted.** The curve is measured under load and applied under load; converting to open-circuit voltage would add error, not remove it.
- **A freshly unplugged full unit correctly reads 100%** even though its loaded terminal voltage is well below 4.2 V — the top anchor is defined by that very state. (While actually charging, SoC remains `None`, unchanged — the charger pulls the terminal voltage up.)
- **Re-derivation requires re-running the bench campaign** (hours per run, several devices). This is the main cost of the decision and why the methodology, tool, and anchors are recorded here. The campaign as run cost six overnight discharges to yield two usable ones — budget for that ratio, not for the ideal.
- **The pinned load must be *verified*, not assumed.** Four of six runs were spoiled by faults that left the workload looking healthy from the outside (solve attempts continued at full rate while nothing actually solved). Any future campaign must check `matches > 0`, not attempt rate, and must confirm the title bar still names a constellation after the SSH session that started the run has ended.
- **Cell aging and per-cell variation** are folded into the pooled fit, not modeled. If observed spread across devices is large, the honest response is fewer/coarser knots, not per-device curves.
