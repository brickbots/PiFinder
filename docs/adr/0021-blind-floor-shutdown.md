# Low battery triggers a software shutdown at the ADC blind floor

When the battery monitor sees **sustained raw-0 battery-voltage reads while running on battery**, PiFinder performs a clean software shutdown through the existing shutdown chokepoint (warning + SHUTDOWN earcon, then the GPIO14 power-off latch per [ADR 0007](0007-gpio-poweroff-latch.md)). The **ADC blind floor** (~3.5 V, see the [Battery CONTEXT](../ax/battery/CONTEXT.md)) thereby becomes the **operational zero** of the discharge curve: 0% means "shutting down now", not "the unknowable voltage at which the boost would eventually die". UI warnings at 10% and 5% state of charge precede it.

Status: accepted; implementation pending. This ADR **narrows [ADR 0006](0006-battery-read-only-telemetry.md) a second time** (as [ADR 0017](0017-battery-fast-charge-config.md) did for register writes): battery telemetry now drives one control action. It also **amends the 0% anchor in [ADR 0020](0020-soc-as-runtime-fraction.md)** — the discharge curve's zero is the blind floor / shutdown point, not the hardware cutoff voltage.

## Context

The first runtime-test campaign (2026-07-17, two rev-4 units) found that below ~3.50 V the BQ25895's one-shot ADC stops completing: battery-voltage reads return raw 0 (decoded as the 2.304 V field offset) while the unit runs on for another 46–72 minutes to an unwarned hard power cut. Three facts drive the decision:

1. **The final stretch is instrument-blind.** No warning of the approaching death is possible below the floor, for us or for the UI — the choice is not "shutdown vs. another monitored hour", it is "predictable, warned end vs. an unpredictable hard cut at an unknown moment within roughly an hour".
2. **The hard cut is harmful.** It is an SD-card-corrupting power loss on a Pi that is writing logs and observations, and it deep-discharges the cell to wherever the boost gives up, costing cell longevity over many cycles.
3. **The blind tail is the worst-measured region of the discharge.** Its duration varied 46 vs 72 minutes between two same-model units (57% spread, versus ~8% spread in total runtime), so no time-based estimate through it deserves trust.

## Decision

- **Trigger: the raw ADC-validity signal, debounced, on battery only.** N consecutive raw-0 BATV reads (3–5 polls ≈ 15–25 s) while `on_external_power` is false. Conversions fail *intermittently* in the 3.50–3.55 V twilight before failing permanently, so a single blind read must never trigger. On external power, blind reads never shut down — a deeply discharged unit on a charger must charge. A unit *booted* on battery below the floor shuts down (warned) almost immediately; that is correct behavior.
- **Never the estimated state of charge.** SoC remains UI-only ("SoC is never a control input" stays true); the shutdown trigger is a hardware-validity fact, not an estimate.
- **Path: the existing chokepoint.** The shutdown flows through the same code path as a user-initiated shutdown (`callbacks.shutdown`): on-screen warning, SHUTDOWN earcon with its ADR-0008 delivery wait, then the kernel power-off that trips the GPIO14 latch. No new power-path mechanism.
- **Warnings precede it.** The UI warns at 10% and 5% estimated state of charge (per the measured discharge curve, these sit roughly 60 and 30 minutes before the floor at typical load). These use SoC because they are advisory UI, which is exactly what SoC is for.

## Considered options

- **Shutdown at the blind floor (chosen).** See Context. Bonus: 0% becomes a *measured and enforced* event, eliminating the extrapolated bottom knots from the discharge curve and removing the high-variance blind tail from the fit entirely.
- **Run to hard cutoff (status quo).** Rejected: unwarned corrupting power loss, deep discharge, and a 0% anchor that is unmeasurable by definition.
- **Blind "reserve mode" countdown.** Show "<10%, ~¾ h reserve" and count down wall-clock time after going blind. Rejected as the primary behavior: the 57% cross-device variance makes it false precision of exactly the kind ADR 0020 rejects — and it still ends in a hard cut.
- **SoC-threshold shutdown (e.g. at 5%).** Rejected: turns an estimate into a control input, and the estimate's error is largest near the bottom of the curve.
- **Hardware fuel gauge.** Out of scope, as in ADR 0020; would obsolete this ADR.

## Consequences

- **~46–72 minutes of blind runtime are forfeited** (~8–11% of a full discharge). The usable-runtime claim becomes ~9 h rather than ~10¼ h — but it ends cleanly, on warning, every time.
- **The discharge curve re-anchors.** For curve fitting, `T_cutoff` becomes the first *sustained* blind read rather than power death. The existing campaign CSVs already contain that moment for both runs — re-anchoring requires an analysis-tool mode, not new bench runs. All knots become measured; none are extrapolated.
- **`BatteryState` must represent blindness.** A raw-0 read is *not* a 2.304 V measurement (see the Battery CONTEXT "blind vs measured-low" ambiguity); the published state needs an explicit invalid/blind representation rather than a decoded artifact, so no consumer can feed 2.304 V into the curve.
- **The Battery context is no longer purely read-only.** ADR 0006's remaining stance is narrowed to: never a *power-path* control (OTG/HIZ/charge-enable stay untouched), and SoC never a control input — but validity-triggered shutdown is now a sanctioned battery-driven action.
- **The blind floor value is empirical.** ~3.50 V was observed identically on two units; the trigger keys on raw-0 reads (the behavior), not on a hard-coded voltage, so per-chip variation in where the floor sits is absorbed automatically.
- A future board with a fuel gauge or a charger whose ADC works to lower voltages would need this revisited, along with 0020's anchors.
