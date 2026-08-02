# BQ25895 Power-Path Design Notes

Reference notes from a design review of the BQ25895 battery charger for use in the new PiFinder hardware. Datasheet: TI SLUSC88C (March 2015, revised October 2022).

## Chip basics

- TI BQ25895 — single-cell Li-ion/Li-polymer I²C-controlled switch-mode charger.
- I²C address: **0x6A** (1101010b + R/W).
- Power-path topology: NVDC (Narrow VDC) — SYS is regulated just above battery voltage when running off VBUS, and switches to the battery via the internal BATFET when VBUS is gone.
- Internal FETs: RBFET (Q1, VBUS↔PMID), HSFET (Q2, PMID↔SW), LSFET (Q3, SW↔PGND), BATFET (Q4, SYS↔BAT).

## Pin map (relevant subset)

| Pin | Role |
|---|---|
| VBUS (1) | Adapter input (3.9–14 V), source of RBFET. |
| PMID (23) | **Internal node** between RBFET and HSFET. Doubles as boost (OTG) output. Only intended to have its bypass cap on it. |
| SW (19,20) | Switching node to external inductor. |
| SYS (15,16) | **System rail.** Regulated by buck when VBUS present, fed from BAT via BATFET when VBUS absent. This is the rail your loads should hang off. |
| BAT (13,14) | Battery terminal. |
| /OTG (8) | Hardware enable for boost mode. Both `/OTG` high *and* `OTG_CONFIG=1` (REG03 bit 5) required to enter boost. |
| /CE (9) | Charge enable, active low. |

## Key registers

| Reg | Bit(s) | Field | Notes |
|---|---|---|---|
| REG00 | 7 | EN_HIZ | Set to 1 to open RBFET (no current from VBUS). Default 0. |
| REG00 | 5:0 | IINLIM | Input current limit (100 mA – 3.25 A). |
| REG02 | 5 | BOOST_FREQ | 0 = 1.5 MHz, 1 = 500 kHz (default). |
| REG02 | 0 | AUTO_DPDM_EN | Auto D+/D- (USB adapter) detection on VBUS insertion. **Default 1.** When 1, each cable insertion re-runs detection and overwrites IINLIM (~500 mA for an SDP). Set to 0 to keep the configured IINLIM across replugs. |
| REG03 | 6 | WD_RST | Write 1 to kick the I²C watchdog. |
| REG03 | 5 | OTG_CONFIG | Boost (OTG) mode enable. **Default 1.** Set to 0 to disable. |
| REG03 | 4 | CHG_CONFIG | Charge enable (default 1). |
| REG03 | 3:1 | SYS_MIN | Minimum SYS voltage floor (3.0–3.7 V, default 3.5 V). |
| REG07 | 5:4 | WATCHDOG | I²C watchdog timer. **00 = disabled**, 01 = 40 s (default), 10 = 80 s, 11 = 160 s. When the watchdog times out, REG03 (and others) reset to defaults — meaning OTG_CONFIG snaps back to 1. |

## Disabling the boost converter from the command line

Goal: persistently disable the OTG/boost converter so PMID never sources voltage from the battery.

```bash
# Disable the I²C watchdog so register writes stick (REG07: 0x9D -> 0x8D)
sudo i2cset -y 1 0x6A 0x07 0x8D

# Clear OTG_CONFIG in REG03 (0x3A default -> 0x1A with bit 5 cleared)
sudo i2cset -y 1 0x6A 0x03 0x1A

# Verify
sudo i2cget -y 1 0x6A 0x03   # expect 0x1A
sudo i2cget -y 1 0x6A 0x07   # expect 0x8D
```

Order matters: kill the watchdog first, otherwise it can re-enable OTG between writes.

These are blind writes that assume otherwise-default REG03/REG07 contents. If you change SYS_MIN, charging timer, etc., do read-modify-write instead.

## Making a fast charge rate survive a cable replug (powered off)

Goal: charge at ~1.5 A and keep it there after the cable is unplugged/replugged while the PiFinder is off. The chip stays battery-powered when the system is off, so its registers persist; the two things that would otherwise revert the input limit are the I²C watchdog (a timeout resets the charge registers) and auto adapter detection (each insertion re-detects and drops IINLIM to ~500 mA). Disable both, then set the limits.

```bash
# 1. Disable the I²C watchdog first so the rest stick (REG07: 0x9D -> 0x8D)
sudo i2cset -y 1 0x6A 0x07 0x8D

# 2. Disable auto D+/D- detection so replugs don't re-detect (REG02 bit0)
#    0x3D default -> 0x3C
sudo i2cset -y 1 0x6A 0x02 0x3C

# 3. Input current limit -> 1500 mA (REG00 IINLIM=0x1C, keep EN_ILIM)
sudo i2cset -y 1 0x6A 0x00 0x5C

# 4. Fast-charge current -> ~1.5 A (REG04 ICHG=0x17 = 1472 mA)
sudo i2cset -y 1 0x6A 0x04 0x17
```

This is what `battery_bq25895.apply_charging_config()` does on every poll (read-modify-write, not blind). It is **not** truly permanent: a full power-on reset (battery fully drained or disconnected) restores `AUTO_DPDM_EN=1`, so the first insertion after that charges slowly until the unit is booted once more. The chip has no non-volatile config; the only software-independent fix is a hardware DCP signature (D+ shorted to D-) so the chip auto-detects a high-current source.

## Disabling VBUS draw (HIZ mode)

To stop drawing from VBUS while keeping the chip alive on battery:

```bash
sudo i2cset -y 1 0x6A 0x00 0x88   # set EN_HIZ=1, keep IINLIM at 500 mA
```

HIZ also stops charging — there is no mode that charges from VBUS while keeping PMID dark, because PMID *is* VBUS (through RBFET) during charging.

## OTG (On-The-Go / boost) mode summary

- Runs the buck converter in reverse: BAT → boosted output on PMID.
- Output: 4.55–5.51 V adjustable (REG0A bits 7:4).
- Output current: up to 3.1 A (REG0A bits 2:0).
- Activated only when both OTG_CONFIG=1 *and* /OTG pin high *and* no VBUS present.
- The intended use is "USB OTG" — letting a battery-powered host source 5 V on the same connector that normally receives charge.

## PMID vs SYS — important architectural point

PMID is **not** a regulated output rail in the normal sense. It has two roles:

1. **VBUS present, charging:** PMID = VBUS minus a small RBFET drop. It's the input bypass node for the buck converter, riding at adapter voltage (anywhere 3.9–14 V).
2. **VBUS absent, OTG enabled:** PMID is the boost output, regulated 4.55–5.51 V.

In the TI reference schematics (Figure 9-1, Figure 9-14) PMID has only its bypass cap (40–60 µF if OTG is used, 8.2 µF if not) and the optional OTG load. The host system is fed from **SYS**, never PMID.

**Takeaway for the new PiFinder board:** any system load currently tied to PMID should be moved to SYS. There is no I²C-only way to keep PMID dark while charging — the fix is in the schematic.

## SYS current limits

| Mode | Limit |
|---|---|
| VBUS feeding buck | **5 A continuous** (I_SYS spec, §7.3) |
| Battery feeding SYS via BATFET | **6 A continuous, 9 A peak ≤1 s** |
| BATFET OCP trip | 9 A |

Adapter must be sized ≥3 A on VBUS to deliver max SYS current per §10.

For a 1S Li-ion (3.0–4.2 V), 5 A on SYS ≈ 18–21 W — way more than a Pi-class load needs.

Thermal: WQFN-24, R_θJA ≈ 31.8 °C/W with PowerPAD soldered. Built-in thermal regulation at 120 °C (T_REG, REG08[1:0]), shutdown at 160 °C.

## SYS rail = 5.1 V?

Not natively achievable on the BQ25895. SYS is a narrow rail clamped just above battery voltage; you can't get 5 V regulated out of a 1S Li-ion via this chip's buck.

Options considered:

1. **Switch to a buck-boost charger** like BQ25798 / BQ25792 / BQ25790 — supports 1S–4S, USB-C PD, can produce higher SYS voltages. Bigger architectural change.
2. **2S battery + buck charger** like BQ25887 — gives a clean ≥5 V SYS naturally. More cells, more cost, more layout area.
3. **Keep the BQ25895 and add an external boost on SYS** — minimum-change path. **Chosen approach.**

## External SYS → 5.1 V boost

Existing build already uses an LM5157 to boost 5.1 V → 17 V for an OLED. LM5157 is a wide-input non-synchronous controller, fine where it sits, but **not** the right pick for the new SYS → 5.1 V stage:

- Non-synchronous (Schottky) costs ~7–9% efficiency at 5 V output.
- Boost ratio of 1.2–1.7× sits in the part's least-efficient region.
- Larger BOM / area than a dedicated low-Vout sync boost.

### Recommended part: **TPS61089**

- Synchronous boost, 5 A integrated switch, 94–96% efficiency at 5 V from Li-ion.
- Input 2.5–12 V, output adjustable 4.5–12 V.
- Internal compensation, programmable Fsw 500 kHz – 2.5 MHz.
- VQFN-12, ~3×3 mm.
- Sized appropriately for a Pi + camera + downstream LM5157 load (~2 A continuous, 3 A peak).

External BOM: ~1 µH inductor (e.g., Coilcraft XAL4020, ≥6 A sat), 22 µF X7R input cap, 22–47 µF X7R output cap, two-resistor FB divider for 5.1 V. No diode (synchronous).

### Alternatives

- **TPS61022** — if continuous load is firmly under 1.5 A; smaller, but likely undersized for the cascaded OLED stage.
- **TPS61288** — 10 A switch class; only worth it if ≥3 A continuous on the 5 V rail.

## Architectural optimization to consider

The current chain is two cascaded boost stages: SYS (3–4.5 V) → 5.1 V → 17 V, ≈ 83% end-to-end for the OLED rail.

LM5157 will accept inputs down to 1.5 V, so it could run directly from SYS (or BAT) and produce 17 V in one stage:
- From 3.7 V → 17 V, duty cycle ≈ 78%, well inside LM5157's ~90% max.
- Single-stage efficiency ≈ 88–90%.
- Eliminates the second conversion entirely for the OLED.

The 5.1 V rail (TPS61089) would then only feed actual 5 V loads, sizing the boost down. Worth evaluating if OLED runtime ever becomes a concern.
