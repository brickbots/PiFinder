# Battery monitor applies a fast-charge configuration at runtime

The battery monitor writes a fixed **fast-charge configuration** to the rev-4 board's TI BQ25895 on every poll: it disables the I²C watchdog (REG07 `WATCHDOG` → 00), raises the input current limit (REG00 `IINLIM`) to ~1.5 A, and raises the fast-charge current (REG04 `ICHG`) to ~1.5 A. Out of reset the chip defaults to a 40 s watchdog, a 500 mA input limit (often lower after "unknown adapter" detection) and 2048 mA charge — and the input limit, not `ICHG`, is the real bottleneck. We want a predictable ~1.5 A charge rate from a known-good 1.5 A source, so software sets it rather than relying on adapter detection or the schematic.

This **supersedes [`0006`](0006-battery-read-only-telemetry.md)**, which adopted the rejected "Monitor + boot-time safety init" option from that ADR — but for charge-rate tuning, not OTG safety. The original OTG reasoning is unchanged: OTG/boost stays disabled **in hardware** via the `/OTG` strap, and software still never writes `OTG_CONFIG`/HIZ/`/CE`. The writes here only ever touch the watchdog and the two current-limit fields.

## Considered options

- **Re-assert the config on every poll (chosen).** The relevant registers are volatile and reset to defaults on a chip reset, a brownout, *or* when the charger re-runs USB adapter detection after a cable is plugged in. A one-shot write at startup would silently revert in all those cases. The per-poll write is a read-modify-write that emits nothing when the registers already match (`plan_charging_writes` returns `[]`), so steady state is three extra reads and zero writes; the cost is paid only when something actually drifted.
- **Write once at power-up.** Matches the literal request but is fragile — the first cable plugged in after boot re-runs adapter detection and drops the input limit back to the detected value.
- **Periodically kick the watchdog (`WD_RST`) instead of disabling it.** Keeps TI's safety timer but needs a write inside every 40 s window and still leaves the current limits at their post-reset defaults. Disabling the watchdog once (and re-asserting if it comes back) is simpler and is what makes the current-limit writes stick.

## Consequences

- **The input-current ceiling is shared with hardware.** `EN_ILIM` (REG00 bit 6) is left set, so the external ILIM-pin resistor remains a hard ceiling and the effective limit is `min(IINLIM register, ILIM pin)`. If that resistor is sized below 1.5 A the register request is clamped and the charge rate stays low — raising it requires a hardware change (or clearing `EN_ILIM`, which removes the backstop and is deliberately *not* done here).
- **The target source must actually supply ~1.5 A.** These writes raise a *limit*; they do not create current. With `ICO_EN` on, the chip still optimises actual draw up to `IINLIM`. The configured charge target is the nearest representable `ICHG` step (1472 mA for a 1500 mA target; 64 mA quantisation).
- The "Battery code never writes the power path" invariant in [`docs/ax/battery/CONTEXT.md`](../ax/battery/CONTEXT.md) is narrowed: software now writes the watchdog and current-limit fields, but still never OTG/HIZ/charge-enable. The conversion-trigger and decode logic are unchanged.
- A later board revision that strapped `/OTG` differently, or removed the ILIM resistor, would need this revisited (as would 0006's OTG analysis).
