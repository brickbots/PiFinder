# INDI Alignment Subsystem — Detection and Disable

## Overview

The INDI library includes an optional alignment subsystem that telescope mount drivers
can use to apply multi-star pointing corrections. For PiFinder, which performs its own
plate-solve–based pointing corrections, the INDI alignment subsystem can **interfere**
by double-correcting coordinates.

This document summarises which drivers expose the alignment subsystem, the INDI
properties involved, and how to disable it programmatically.

---

## Affected Drivers

Five INDI drivers (or driver families) that expose the alignment subsystem are
relevant to PiFinder users:

| Driver key       | INDI Device Name          | Class inheritance                         | Notes |
|------------------|---------------------------|-------------------------------------------|-------|
| `skywatcher_altaz` | `Skywatcher Alt-Az`     | `AlignmentSubsystemForDrivers`            | Forces subsystem ON in `initProperties()` |
| `astrotrac`      | `AstroTrac`               | `AlignmentSubsystemForDrivers`            | Forces subsystem ON in `initProperties()` |
| `dsc`            | `Digital Setting Circle`  | `AlignmentSubsystemForDrivers`            | Standard initialisation (starts OFF) |
| `eqmod`          | `EQMod Mount`             | Conditional on `WITH_ALIGN` compile flag  | Has its own `ALIGNMODE` switch **and** the standard subsystem |
| `celestronaux`   | `Celestron AUX`           | `AlignmentSubsystemForDrivers`            | Standard initialisation (starts OFF) |

### Why only these five?

- **41+ other drivers** (10Micron, OnStep, Rainbow, AM5, Gemini, StarBook, …) rely on
  the mount's own firmware pointing model and do **not** inherit from
  `AlignmentSubsystemForDrivers`.
- **Telescope Simulator** and **EQMod** implement additional pointing models in
  software, but the Telescope Simulator is not used with real hardware.

---

## How the Subsystem Works

The INDI alignment subsystem is implemented in
`indi/libs/alignment/MathPluginManagement.cpp` and exposes these properties:

### Standard alignment property (all five drivers)

| INDI Property name          | Type   | Element                          | Default | Meaning |
|-----------------------------|--------|----------------------------------|---------|---------|
| `ALIGNMENT_SUBSYSTEM_ACTIVE`| Switch | `ALIGNMENT SUBSYSTEM ACTIVE`     | Off     | Master on/off switch |
| `ALIGNMENT_SUBSYSTEM_MATH_PLUGINS` | Switch | Plugin names | varies | Active math plugin |
| `ALIGNMENT_SUBSYSTEM_MATH_PLUGIN_INITIALISE` | Switch | `ALIGNMENT SUBSYSTEM MATH PLUGIN INITIALISE` | Off | Re-init plugin |

> **Note:** `skywatcherAPIMount` and `AstroTrac` override the default and set
> `ALIGNMENT_SUBSYSTEM_ACTIVE` to **On** unconditionally in `initProperties()`.

When `ALIGNMENT_SUBSYSTEM_ACTIVE` is `On`, every coordinate transformation (sky →
mount and mount → sky) goes through the alignment math plugin, even if no sync points
have been added.

### EQMod-specific alignment property

EQMod has its own alignment mode switch **in addition** to the standard property above:

| INDI Property name | Type   | Element        | Meaning |
|--------------------|--------|----------------|---------|
| `ALIGNMODE`        | Switch | `NOALIGN`      | No alignment (pass-through) |
|                    |        | `ALIGNNEAREST` | Nearest-point interpolation |
|                    |        | `ALIGNSYNC`    | Sync-based correction |
|                    |        | `ALIGNSYNCSKIP`| Sync-based, skip first |

When `NOALIGN` is `On`, EQMod sends raw encoder coordinates with no correction.

---

## Disabling the Alignment Subsystem via INDI XML

The INDI server communicates over TCP port 7624 using an XML protocol.
To disable alignment, send a `newSwitchVector` command:

### For SkywatcherAPIMount, AstroTrac, DSC, CelestronAUX

```xml
<newSwitchVector device="Skywatcher Alt-Az" name="ALIGNMENT_SUBSYSTEM_ACTIVE">
  <oneSwitch name="ALIGNMENT SUBSYSTEM ACTIVE">Off</oneSwitch>
</newSwitchVector>
```

Replace `Skywatcher Alt-Az` with the actual device name (see table above).

### For EQMod Mount — step 1: disable own alignment

```xml
<newSwitchVector device="EQMod Mount" name="ALIGNMODE">
  <oneSwitch name="NOALIGN">On</oneSwitch>
</newSwitchVector>
```

### For EQMod Mount — step 2: disable INDI subsystem (if compiled with WITH_ALIGN)

```xml
<newSwitchVector device="EQMod Mount" name="ALIGNMENT_SUBSYSTEM_ACTIVE">
  <oneSwitch name="ALIGNMENT SUBSYSTEM ACTIVE">Off</oneSwitch>
</newSwitchVector>
```

---

## Detection Approach

To detect whether the alignment subsystem is active for a connected device, PiFinder:

1. Connects to the INDI server (default `localhost:7624`).
2. Sends `<getProperties version="1.7"/>` to receive all property definitions.
3. For each driver configuration entry, checks whether the target device is present
   and the detection property/element has the "active" value.

| Driver           | Detection property | Detection element                | Active when |
|------------------|--------------------|----------------------------------|-------------|
| skywatcher_altaz | `ALIGNMENT_SUBSYSTEM_ACTIVE` | `ALIGNMENT SUBSYSTEM ACTIVE` | `On` |
| astrotrac        | `ALIGNMENT_SUBSYSTEM_ACTIVE` | `ALIGNMENT SUBSYSTEM ACTIVE` | `On` |
| dsc              | `ALIGNMENT_SUBSYSTEM_ACTIVE` | `ALIGNMENT SUBSYSTEM ACTIVE` | `On` |
| eqmod            | `ALIGNMODE`        | `NOALIGN`                        | `Off` (another mode is selected) |
| celestronaux     | `ALIGNMENT_SUBSYSTEM_ACTIVE` | `ALIGNMENT SUBSYSTEM ACTIVE` | `On` |

---

## Configuration File

PiFinder reads **two** YAML configuration files at startup, merging them:

1. **In-repository** (`indi_disable_alignment.yml` at the repository root)
   — default disable commands for all known drivers.
2. **User override** (`~/PiFinder_data/indi_disable_alignment.yml`)
   — per-user overrides. Rules:
   - If a driver key is present and has a non-empty `disable_commands` list →
     the user's list **replaces** the repository list for that driver.
   - If a driver key is present and has an **empty** `disable_commands: []` →
     detection is kept, but no disable commands are sent for that driver.
   - If a driver key is absent from the user file → repository defaults are used.

See `indi_disable_alignment.yml` at the repository root for the full format and
all default entries.

---

## Web Interface

The PiFinder web server exposes an **INDI** page (`/indi`) showing:

- INDI server connection status
- For each configured driver: detection result and disable result
- A button to copy the repository YAML to the user data directory (with diff preview
  if the user file was manually edited)
- Current INDI device and property summary
