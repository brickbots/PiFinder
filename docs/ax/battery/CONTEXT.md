# Battery (Power & Charging)

The Battery context reads battery voltage and charge state from the rev-4 on-board **BQ25895** charger over I²C and publishes a `BatteryState` into shared state. It is **mostly telemetry**: the only writes are a one-shot ADC conversion trigger and a fixed **fast-charge configuration** (disable the I²C watchdog, disable automatic USB adapter detection, set the input and fast-charge current limits to ~1.5 A) re-asserted on each poll — see [ADR 0017](../../adr/0017-battery-fast-charge-config.md). Disabling adapter detection is what lets the input limit survive a cable replug while the unit is powered off. It never touches OTG/HIZ/charge-enable; OTG/boost is disabled in hardware. The user-facing docs call this domain "Power & Charging"; the *code* uses the `battery_` prefix to stay clear of the unrelated sleep/wake `power_state`.

> Companion design notes: [`../../bq25895_design_notes.md`](../../bq25895_design_notes.md) (chip behaviour, power path, register map).

## Language

### Battery state

**Battery voltage**:
The measured single-cell Li-ion terminal voltage, in volts. The **canonical** battery reading and the source of truth — everything else about charge is derived from it. The BQ25895 has no fuel gauge, so this is the only thing actually *measured*.
_Avoid_: "battery level" (ambiguous — see Flagged ambiguities), "charge level".

**State of charge** (a.k.a. battery percent):
A coarse 0–100% **estimate of the fraction of typical-load runtime remaining**, derived from battery voltage through the **discharge curve** — see [ADR 0020](../../adr/0020-soc-as-runtime-fraction.md). It answers "how much longer will it run?", *not* "what fraction of the cell's capacity is left" (capacity fraction is unmeasurable on this hardware). UI-only, never a control input, and **undefined while charging** (the charger pulls the terminal voltage up, so a percentage would lie) — represented as `None` in that case.
_Avoid_: treating it as a measured quantity, "capacity fraction", "fuel gauge" (there isn't one), "battery level".

**Discharge curve**:
The measured relationship between battery voltage and remaining-runtime fraction under the **typical load**, captured by bench **runtime tests** (full charge → hard cutoff). The source of the state-of-charge lookup knots. Anchored at both ends by real events: 100% is the under-load voltage right after unplugging a fully charged unit; 0% is the **cutoff voltage**.
_Avoid_: textbook Li-ion capacity curves (different x-axis), "battery curve" (vague).

**Typical load**:
The pinned reference workload under which runtime and the discharge curve are defined: continuous capture-and-solve with the screen on and display sleep off. Runtime claims and state-of-charge percentages are statements *about this load*; lighter real-world use (e.g. display asleep between looks) runs longer than the estimate says.
_Avoid_: "average use" (unpinned, unmeasurable).

**Cutoff voltage**:
The battery voltage at which the hardware actually dies — the SYS boost loses regulation and the unit hard-powers-off, with no graceful shutdown. An observed property of the board + cell, not a chosen threshold. In practice it is **not directly measurable**: it lies below the **ADC blind floor**, so no run ever records it — which is why the **low-battery shutdown** preempts it and the discharge curve's 0% anchors to the blind floor instead (see [ADR 0021](../../adr/0021-blind-floor-shutdown.md)).
_Avoid_: conflating with the **low-battery shutdown** (software, warned, at the blind floor — the cutoff is the hardware death it preempts).

**Low-battery shutdown**:
The software-initiated clean shutdown triggered by **sustained raw-0 battery-voltage reads while on battery** (the debounced signature of crossing the **ADC blind floor**) — see [ADR 0021](../../adr/0021-blind-floor-shutdown.md). The operational end of a discharge and the discharge curve's 0%. Triggered by the ADC-validity signal, never by the estimated **state of charge**; flows through the same chokepoint as a user shutdown (warning, SHUTDOWN earcon, GPIO14 latch). Never fires on external power.
_Avoid_: "auto power-off" (vague), triggering language framed in SoC percentages (the trigger is a hardware-validity fact, not an estimate).

**ADC blind floor** (~3.5 V):
The battery voltage below which the BQ25895's one-shot ADC conversions stop completing: the ADC result registers read raw 0, which decodes to each field's *offset* (battery voltage 2.304 V, VBUS 2.6 V) — an artifact, not a measurement. Conversions fail intermittently just below the floor, then permanently. Observed at the same reading (3.504 V) on both rev-4 units in the first runtime-test campaign; the unit keeps running well past it (46–72 min under the typical load), so the final stretch of every discharge is **instrument-blind** — the field UI included. The charger's *status* bits (charge status, power source) are plain register reads, not conversions, and stay live below the floor. Everything below the floor — including the discharge curve's bottom knots — is extrapolation.
_Avoid_: treating a raw-0 decode (2.304 V) as a measured battery voltage; "ADC failure/fault" (it is repeatable low-battery chip behavior, not a defect).

**Charge status**:
Which charge phase the charger reports: **Not charging / Pre-charge / Charging (fast) / Charged (done)**. A property of the charger's state machine, distinct from whether external power is present.
_Avoid_: conflating with **power source** — "charging" and "on external power" are different facts.

**Power source** (`on_external_power`):
Whether the unit is currently running from USB/adapter input (input present and power-good) versus from the battery. You can be on external power and **not** charging (e.g. charge complete), so this is reported separately from **charge status**.
_Avoid_: "plugged in" (says nothing about power-good), implying it from charge status.

**`BatteryState`**:
The published dataclass carried in `SharedStateObj` (`shared_state.battery()` / `set_battery()`). Holds **battery voltage**, **charge status**, **power source**, the estimated **state of charge**, the cheap adjacent diagnostics (charge current, VBUS voltage, SYS voltage) and a timestamp. Read-only for consumers. `None` when no charger is present (rev-3 hardware).
_Avoid_: "battery info", "power state" (collides with the sleep/wake `power_state`).

### Hardware presence

**`HardwareCapabilities`**:
The startup-detected record of which optional hardware is present on this board (e.g. `has_bq25895`, with room to grow). Built once by `hardware_detect` and published into `SharedStateObj` (`shared_state.hardware()` / `set_hardware()`) as the single source of truth for rev-dependent decisions. Distinct from `hardware_platform` (the `"Pi"`/`"Fake"` selector string).
_Avoid_: "hardware platform", "config" (it's detected at runtime, not user-set).

**Hardware probe**:
A non-destructive I²C presence check (`hardware_detect.i2c_present(address, bus)`, confirmed by reading the BQ25895 part-number register) used at startup to populate `HardwareCapabilities`. The battery monitor only spawns when the charger is detected.
_Avoid_: "scan", "autodetect" (reserve for the camera-type detection).

### Power path (hardware, not software)

**OTG / boost**:
The charger's reverse-boost mode (battery → 5 V out). On rev-4 it is disabled **in hardware** (the `/OTG` pin is strapped low), so software never manages it — software's only power-path writes are the fast-charge config (watchdog + current limits, see [ADR 0017](../../adr/0017-battery-fast-charge-config.md)), never `OTG_CONFIG`. Not to be confused with the external **SYS → 5.1 V boost** (a separate TPS61088 part).
_Avoid_: implying software enables/disables OTG.

**Power-off latch** (GPIO14):
The rev-4 hardware power-down path. At kernel power-off the `gpio-poweroff` device-tree overlay drives **GPIO14 low**, tripping the **LTC2954** power-button controller's KILL input; the LTC2954 drops **EN** on the **TPS61088** SYS boost and the system loses power. It is **active-low and fail-safe**: GPIO14 carries a hardware pull-up, so the pin sits high (power on) through early boot and reboot, and only the kernel power-off handler ever pulls it low. This is a *firmware / device-tree* mechanism provisioned in `pifinder_setup.sh` (see ADR 0007) — **not** application code: no Python drives the kill line; the kernel drives it once, at shutdown. (The Battery monitor does write the charger's watchdog and current-limit registers per [ADR 0017](../../adr/0017-battery-fast-charge-config.md), but never this latch.) Added for every board; a no-op on rev-3, which has no latch.
_Avoid_: calling it a "shutdown command" (it's a hardware kill line, not a syscall); implying the Battery monitor or any Python code drives it.

## Flagged ambiguities

- **"battery level"** (bare) — do not use. It conflates the *measured* **battery voltage** with the *estimated* **state of charge**. Name one: voltage (measured, canonical) or state-of-charge % (estimated, UI-only, `None` while charging).
- **State of charge is a runtime fraction, not a capacity fraction** — the BQ25895 measures charge current only (no discharge current, no coulomb counter), so "% of capacity left" cannot be measured; "% of typical-load runtime left" can (see ADR 0020). Don't describe the percentage in capacity terms.
- **Blind vs measured-low** — a decoded battery voltage of exactly 2.304 V is never a real reading; it is the raw-0 decode below the **ADC blind floor**. Consumers must distinguish "measured low (~3.5 V)" from "blind (raw 0 — below the floor, unknown how far)". Feeding the decode into the discharge curve yields a fake 0%.
- **`power_state` / `PowerManager`** — these are the **display sleep/wake** concept (`0`=sleep, `1`=awake) and have **nothing** to do with the battery or charger. The Battery context deliberately uses the `battery_` prefix to avoid this collision. Never reach for `power_*` names in charger code.
- **"charging" vs "on external power"** — separate facts. Charge status reports the charger's phase; power source reports whether input power is present. A unit on external power with a full cell is "on external power, not charging".
- **`BatteryState` is `None` vs 0%** — `None` means *no charger detected* (rev-3 board, monitor not running); a real `BatteryState` with a low `state_of_charge_pct` means *detected and nearly empty*. Consumers must distinguish "no battery hardware" from "empty battery".

## Example dialogue

> **Dev:** The status line should show battery level — what field do I read?
>
> **Domain:** Don't say "battery level". Read `BatteryState.battery_voltage` for the real measured value; if you want a percentage, read `state_of_charge_pct`, but it's a rough estimate off a voltage curve and it's `None` whenever we're charging — show the voltage or a "charging" state then, not a fake number.
>
> **Dev:** What if the board has no charger?
>
> **Domain:** `shared_state.battery()` returns `None`. That's distinct from a low battery. Gate the whole row on `has_bq25895` in `shared_state.hardware()` — same fact that decides whether the monitor process runs at all.
>
> **Dev:** Do we ever turn charging on/off from software?
>
> **Domain:** No — we never touch charge-enable (`/CE`) or OTG; OTG is disabled in hardware via the `/OTG` strap. We *do* set the charge *rate*: the monitor writes the input and fast-charge current limits to ~1.5 A and disables the I²C watchdog on every poll so those limits stick (ADR 0017). Beyond reads and the one-shot ADC trigger, those watchdog/current-limit writes are the only ones — enabling/disabling charging itself stays the schematic's job.
