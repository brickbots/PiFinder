# State of charge means remaining-runtime fraction under typical load

The state-of-charge percentage shown in the UI is defined as the **expected fraction of typical-load runtime remaining**, and its voltage→percent lookup (`SOC_LUT` in `battery_bq25895.py`) is to be derived from **measured bench discharge runs** of real PiFinder rev-4 units — not from a textbook Li-ion capacity curve.

Status: methodology decided and the CONTEXT.md terms sharpened now; the measured knots land in a later change once the first runtime-test campaign completes. Until then the shipped LUT is unchanged (generic Li-ion folklore, annotated as such in the code).

## Context

The BQ25895 has no fuel gauge. Its ADC measures battery terminal voltage and **charge** current only — there is no discharge-current measurement and no coulomb counter, so "fraction of capacity remaining" is not observable on this hardware, at any effort level. What a bench run *can* observe, exactly, is **time**: run a fully charged unit under a fixed workload until the hardware dies, log voltage the whole way, and every sample is a known distance-in-time from cutoff.

The workload is pinned (the **typical load**: continuous capture-and-solve, screen on, display sleep off) because terminal voltage under load is what the chip reads in the field; a curve measured at a different load would systematically mis-map voltage to runtime.

## Decision

- **Semantics:** SoC(v) = expected fraction of remaining runtime under the typical load. 100% is the under-load voltage immediately after unplugging a full unit (not the 4.2 V charge-termination voltage, which a loaded cell never reads); 0% is the observed **cutoff voltage** where the SYS boost loses regulation and the unit hard-powers-off.
- **Derivation:** for each bench run, assign each telemetry sample SoC(t) = (T_cutoff − t) / (T_cutoff − T_unplug), pair it with the sampled voltage, pool the samples across runs and devices, and fit piecewise-linear knots on that scatter → new `SOC_LUT`.
- **Reproducibility:** the analysis tool and the derived knots merge together (the imu2cam-tool precedent), so the curve can be re-derived when hardware or workload changes. The raw telemetry logs are retained outside the repo. The bench harness lives on the never-merged `battery-runtime-test` branch on origin, whose root `BATTERY_RUNTIME_TEST.md` is the operational runbook (deploy, run, collect, analyze).

## Considered options

- **Remaining-runtime fraction (chosen).** Directly measurable from a discharge run; anchors 0% and 100% to real events on real hardware; answers the question users actually ask of a battery indicator ("how much longer?").
- **Generic Li-ion capacity curve, knots nudged by observation.** Keeps textbook semantics but the middle knots stay unmeasurable folklore — nothing on this board can validate "50% of capacity". Rejected as claiming precision we cannot check.
- **Coulomb counting in software.** Impossible: no discharge-current measurement exists on the BQ25895.
- **Add a fuel-gauge part.** A hardware change, out of scope for a software estimate; would obsolete this ADR if it ever happened.

## Consequences

- **The percentage is a statement about the typical load.** Lighter use (display asleep between looks, shorter exposures) drains slower *and* reads a higher voltage at equal runtime-fraction, so the estimate is conservative there; sustained heavier-than-typical use would make it optimistic. Acceptable for a UI-only estimate (see [ADR 0006](0006-battery-read-only-telemetry.md) lineage — it is never a control input).
- **No rest-voltage correction is needed or wanted.** The curve is measured under load and applied under load; converting to open-circuit voltage would add error, not remove it.
- **A freshly unplugged full unit correctly reads 100%** even though its loaded terminal voltage is well below 4.2 V — the top anchor is defined by that very state. (While actually charging, SoC remains `None`, unchanged — the charger pulls the terminal voltage up.)
- **Re-derivation requires re-running the bench campaign** (hours per run, several devices). This is the main cost of the decision and why the methodology, tool, and anchors are recorded here.
- **Cell aging and per-cell variation** are folded into the pooled fit, not modeled. If observed spread across devices is large, the honest response is fewer/coarser knots, not per-device curves.
