# Battery monitoring is read-only; the BQ25895 power path is managed in hardware

> **Superseded by [`0017-battery-fast-charge-config.md`](0017-battery-fast-charge-config.md).** The "Monitor + boot-time safety init" option rejected below was later adopted (for charge-rate tuning, not OTG safety): the battery monitor now disables the I²C watchdog and raises the input/charge current limits on every poll. The OTG analysis here still holds — OTG/boost remains disabled in hardware by the `/OTG` strap, and software still never touches `OTG_CONFIG`/HIZ/charge-enable.

The rev4 board uses a TI BQ25895 I²C charger. We treat it as a **read-only telemetry source**: the `battery_` code reads battery voltage, charge status, power source and a few diagnostics, and never configures the power path (no OTG/HIZ/input-current-limit/charge-enable writes). This is safe because OTG/boost is disabled **in hardware** — the `/OTG` pin is strapped low, so `OTG_CONFIG` is irrelevant and there is nothing for software to keep in check. The one write the code does make is pulsing REG02 to start a one-shot ADC conversion, which is a telemetry trigger, not power-path control.

## Considered options

- **Read-only (chosen).** Possible only because the `/OTG` strap removes the need for any runtime power-path management.
- **Monitor + boot-time safety init.** Would be required if `/OTG` were *not* strapped: the I²C watchdog (REG07, default 40 s) resets REG03 to defaults and re-enables `OTG_CONFIG` after every timeout, so software would have to disable the watchdog and clear `OTG_CONFIG` on every boot (REG07 is volatile and resets on power-cycle). The hardware strap makes this unnecessary.
- **Full driver** (OTG/HIZ/current-limit/ship-mode). Far more surface area than the need ("read battery level and charge status"), and pointless once the power path is fixed in the schematic.

## Consequences

- A future reader who expects a typical BQ25895 driver to manage charging will find only reads — this is deliberate, not an omission. Charging behaviour lives in the schematic (see [`docs/bq25895_design_notes.md`](../bq25895_design_notes.md)).
- If a later board revision stops strapping `/OTG` low, read-only is **no longer safe** and this decision must be revisited (the boot-time safety-init option above becomes mandatory).
- Battery state of charge is an *estimate* off a voltage curve, not a measured value — the chip has no fuel gauge. See the glossary at [`docs/ax/battery/CONTEXT.md`](../ax/battery/CONTEXT.md).
