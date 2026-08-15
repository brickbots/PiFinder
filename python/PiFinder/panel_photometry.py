#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Camera-as-photometer bench rig for panel brightness characterization.

Turns the PiFinder's own IMX462 (lensless, ~1 cm from the panel, dark
enclosure) into a photometer and drives a panel's brightness axes while
measuring the light they actually produce. Vocabulary — photometer rig, panel
flux, exposure ladder, tier, dark floor, sentinel — is defined in
docs/ax/display/CONTEXT.md; the SSD1333 axes themselves in ADR 0023.

The rig integrates flux; it cannot resolve panel pixels. Spatial artifacts
(blooming, smear, LUT artifacts) stay eyeball-judged — use
``PiFinder.precharge_sweep`` for those.

Every measurement reduces to one unit, panel flux: bias-subtracted mean raw
ADU over the sensor ROI per second of actual (metadata-reported) exposure.
Measurements across the ~4-decade output range are made comparable by an
exposure ladder of fixed tiers, cross-calibrated empirically at run start —
nominal exposure times are never trusted for tier ratios.

Usage (stop the PiFinder service first — this owns the SPI panel, the camera,
the keypad PWM and the status LEDs):

    python3 -m PiFinder.panel_photometry selftest --panel ssd1333
    python3 -m PiFinder.panel_photometry measure --panel ssd1333 \\
        --axes contrast=64,master=7 --value 255
    python3 -m PiFinder.panel_photometry sweep --panel ssd1333 \\
        --spec spec.json --out run.jsonl [--resume]

Sweep spec JSON:

    {
      "description": "contrast 1-D sweep at reference",
      "pinned": {"master": 7, "ceiling": 31, "precharge": 23},
      "frames": 4,
      "sentinel_every": 25,
      "points": [
        {"axes": {"contrast": 4}, "value": 255},
        {"axes": {"contrast": 8}, "value": 255}
      ]
    }

Each point's axes = panel reference values, overlaid with ``pinned``, overlaid
with the point's own ``axes``. Results append to a JSONL journal, one record
per point, plus periodic ``sentinel`` records (a fixed dim state re-measured
beat-free to expose thermal drift). ``--resume`` skips points already journaled.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

MEASUREMENTS_DIR = Path(__file__).resolve().parents[2] / "docs/ax/display/measurements"

#: Fallback exposure tiers (µs), longest first, used only when the refresh
#: period cannot be measured. The real ladder is built at rig bring-up as
#: integer multiples of the measured panel refresh period (see
#: ``Rig.measure_refresh``): a whole number of refresh periods integrates the
#: same energy whatever the phase, so those tiers are immune to the panel's
#: PWM beat (measured: 30% frame-to-frame CV at 1 ms, 0.1% at one period).
DEFAULT_TIERS_US = [1_000_000, 100_000, 10_000, 1_000]

#: Refresh multiples the ladder is built from, plus the sub-period tier.
LADDER_PERIODS = (64, 8, 1)

#: The one deliberately sub-refresh-period tier, for states too bright to
#: expose for a full period. Beat can't be nulled below one period, so
#: measurements here average many frames instead.
SUB_PERIOD_TIER_US = 1_000

#: Frames averaged on the sub-period tier: beat CV ~30% single-frame, so 48
#: frames give ~4% — adequate where it's used (the bright regime's per-press
#: steps are ~35%).
SUB_PERIOD_FRAMES = 48

#: One analog gain for every measurement, ever. Range comes from the exposure
#: ladder; a second varying gain would double the cross-calibration surface.
ANALOG_GAIN = 1.0

#: A frame counts as saturated when its ROI p99.9 exceeds this fraction of
#: full scale; the measurement then drops to a shorter tier.
SATURATION_FRACTION = 0.98

#: Dark-subtracted R-plane mean (ADU) below which a longer tier is preferred.
LOW_SIGNAL_ADU = 100.0

FRAMES_PER_MEASUREMENT = 4

#: Frames discarded after any control change before measured frames are taken
#: (the pipeline delivers transitional frames at stale exposures).
FLUSH_FRAMES = 2

#: Wait between programming panel state and capturing (SPI + refresh settle).
SETTLE_SECONDS = 0.2


# ---------------------------------------------------------------------------
# Stray light
# ---------------------------------------------------------------------------


class Lights:
    """Douses every light the camera could see besides the panel.

    Status LEDs (PWR, ACT, ...) via sysfs — every entry under
    /sys/class/leds is doused, previous trigger/brightness restored on exit —
    and the keypad backlight via hardware PWM channel 1 at duty 0.
    """

    LEDS_ROOT = Path("/sys/class/leds")

    def __init__(self):
        self._saved = {}
        self._pwm = None

    def douse(self):
        import subprocess

        for led in sorted(self.LEDS_ROOT.iterdir()) if self.LEDS_ROOT.is_dir() else []:
            try:
                trigger = (led / "trigger").read_text()
                current = trigger[trigger.index("[") + 1 : trigger.index("]")]
                brightness = (led / "brightness").read_text().strip()
                self._saved[led.name] = (current, brightness)
                subprocess.run(
                    [
                        "sudo",
                        "sh",
                        "-c",
                        f"echo none > {led}/trigger; echo 0 > {led}/brightness",
                    ],
                    check=True,
                    capture_output=True,
                )
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                print(f"warning: could not douse LED {led.name}: {error}")

        try:
            from rpi_hardware_pwm import HardwarePWM

            self._pwm = HardwarePWM(pwm_channel=1, hz=120)
            self._pwm.start(0)
        except Exception as error:  # rig must run even if PWM is absent
            print(f"warning: could not zero keypad backlight: {error}")

    def restore(self):
        import subprocess

        for name, (trigger, brightness) in self._saved.items():
            led = self.LEDS_ROOT / name
            try:
                subprocess.run(
                    [
                        "sudo",
                        "sh",
                        "-c",
                        f"echo {trigger} > {led}/trigger; "
                        f"echo {brightness} > {led}/brightness",
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as error:
                print(f"warning: could not restore LED {name}: {error}")
        self._saved.clear()


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


class Panel:
    """A panel as a named set of brightness axes plus a uniform test frame.

    ``axes`` maps axis name -> (lo, hi, reference). The reference values are
    the state 1-D sweeps pin the other axes at; for calibrated axes they are
    the values the shipped policy's constants were measured at.
    """

    name: str = ""
    axes: dict = {}
    #: Axis values for the drift sentinel — dim enough that one refresh
    #: period of exposure doesn't saturate, so sentinels measure beat-free
    #: at ~0.2% precision, which is what makes slow drift visible at all.
    sentinel_axes: dict = {}

    def __init__(self):
        self.display = self._make_display()
        self._state = {axis: ref for axis, (_, _, ref) in self.axes.items()}
        self._value = None

    def _make_display(self):
        raise NotImplementedError

    def _program(self, axis, value):
        raise NotImplementedError

    def reset(self):
        """Leaves the panel the way the app expects to find it."""
        raise NotImplementedError

    def set_state(self, axis_values, pixel_value):
        """Programs all axes and shows a full-screen uniform frame.

        Axes not named fall back to their reference values. Always programs
        every axis and redraws: render-side axes (the SSD1333 gray scale
        ceiling) only take effect at display time, and unconditional
        reprogramming keeps a sweep's points order-independent.
        """
        for axis, (lo, hi, ref) in self.axes.items():
            value = axis_values.get(axis, ref)
            if not lo <= value <= hi:
                raise ValueError(f"{axis}={value} outside [{lo}, {hi}]")
            self._program(axis, value)
            self._state[axis] = value
        self._show(pixel_value)

    def _show(self, pixel_value):
        if not 0 <= pixel_value <= 255:
            raise ValueError(f"pixel value {pixel_value} outside [0, 255]")
        image = Image.new("RGB", self.display.resolution, (pixel_value, 0, 0))
        self.display.device.display(image.convert(self.display.device.mode))
        self._value = pixel_value

    def blank(self):
        self._show(0)

    def state(self):
        return dict(self._state, value=self._value)

    def reference_state(self):
        return {axis: ref for axis, (_, _, ref) in self.axes.items()}


class SSD1333Panel(Panel):
    """The 1.91" 176x176 panel: four axes (see ADR 0023).

    Reference values are the calibration anchors of the shipped policy:
    pre-charge 0x17 and the full gray scale ceiling, with the drive registers
    at a mid state (contrast 64, master 7) that no exposure tier clips.
    """

    name = "ssd1333"
    axes = {
        "contrast": (0, 255, 64),
        "master": (0, 15, 7),
        "ceiling": (2, 31, 31),
        "precharge": (0, 31, 0x17),
    }
    # Measured ~2.2e5 ADU/s on the rig: ~3100 ADU at one refresh period.
    sentinel_axes = {"contrast": 4, "master": 3}

    def _make_display(self):
        from PiFinder.displays import DisplaySSD1333

        return DisplaySSD1333()

    def _program(self, axis, value):
        device = self.display.device
        if axis == "contrast":
            device.contrast(value)
        elif axis == "master":
            device.master_brightness(value)
        elif axis == "ceiling":
            device.gray_scale_ceiling(value)
        elif axis == "precharge":
            device.precharge_voltage(value)

    def reset(self):
        self.display.device.precharge_voltage(0x17)
        self.display.set_brightness(125)
        self.blank()


class SSD1351Panel(Panel):
    """The original 1.27" 128x128 panel: the two axes the driver exposes.

    Its controller has more (gray table, pre-charge) that nobody has
    characterized; add them here when the driver grows commands for them.
    """

    name = "ssd1351"
    axes = {
        "contrast": (0, 255, 128),
        "master": (0, 15, 7),
    }
    # Untested guess; auto-ranging keeps it valid whatever the true flux.
    sentinel_axes = {"contrast": 16, "master": 3}

    def _make_display(self):
        from PiFinder.displays import DisplaySSD1351

        return DisplaySSD1351()

    def _program(self, axis, value):
        if axis == "contrast":
            self.display.device.contrast(value)
        elif axis == "master":
            self.display.device.command(0xC7, value)

    def reset(self):
        self.display.set_brightness(125)
        self.blank()


PANELS = {cls.name: cls for cls in (SSD1333Panel, SSD1351Panel)}


# ---------------------------------------------------------------------------
# Photometer
# ---------------------------------------------------------------------------


class Photometer:
    """The lensless IMX462 as a fixed-gain, ladder-ranged light meter.

    Captures raw Bayer frames, reduces the central ROI to per-plane
    statistics, and converts the R plane (the panel is red) to panel flux in
    ADU/s using each frame's actual metadata exposure and the run's measured
    dark floors and tier scales.
    """

    def __init__(self, tiers_us=None, gain=ANALOG_GAIN):
        from picamera2 import Picamera2
        from PiFinder.sqm import detect_camera_type, get_camera_profile

        self.camera = Picamera2()
        self.camera_type = detect_camera_type(self.camera.camera.id)
        self.profile = get_camera_profile(self.camera_type)
        self.gain = gain
        self.tiers_us = sorted(tiers_us or DEFAULT_TIERS_US, reverse=True)
        self.refresh_us = None  # measured panel refresh period, if known
        self._current_tier = None
        self.dark = {}  # tier_us -> per-plane dark-floor means
        self.tier_scale = {}  # tier_us -> multiplier onto the top tier's scale
        self.full_scale = 2**self.profile.bit_depth - 1

        config = self.camera.create_still_configuration(
            {"size": (512, 512)},
            raw={"size": self.profile.raw_size, "format": self.profile.format},
        )
        self.camera.configure(config)
        self.camera.set_controls({"AeEnable": False, "AnalogueGain": self.gain})
        self.camera.start()

    def close(self):
        self.camera.stop()
        self.camera.close()

    def _set_tier(self, tier_us):
        if tier_us == self._current_tier:
            return
        self.camera.set_controls({"ExposureTime": int(tier_us)})
        self._current_tier = tier_us
        # Controls land several frames later, and how many varies. Flush
        # until the pipeline reports the requested exposure — or, for a tier
        # the driver clamps, until the report has clearly settled on one
        # different-from-requested value.
        # Tolerance must stay below the refresh-scan's 100us fine step or
        # small exposure changes would be mistaken for already-settled.
        tolerance = max(30.0, 0.005 * tier_us)
        seen = []
        for _ in range(12):
            request = self.camera.capture_request()
            reported = request.get_metadata().get("ExposureTime")
            request.release()
            seen.append(reported)
            if reported is not None and abs(reported - tier_us) <= tolerance:
                return
            if len(seen) >= 6 and len({s for s in seen[-3:]}) == 1:
                return
        print(f"warning: tier {tier_us}us never settled; reports were {seen}")

    def _grab(self):
        """One raw frame -> (per-plane ROI stats, actual exposure seconds)."""
        request = self.camera.capture_request()
        raw = request.make_array("raw").copy().view(np.uint16)
        metadata = request.get_metadata()
        request.release()

        cropped = self.profile.crop_and_rotate(raw)
        rows, cols = cropped.shape
        # Central 50% ROI, start indices forced even so Bayer parity matches
        # the crop origin (the profile crops by even offsets).
        r0, c0 = (rows // 4) & ~1, (cols // 4) & ~1
        roi = cropped[r0 : r0 + rows // 2, c0 : c0 + cols // 2]
        planes = {
            "R": roi[0::2, 0::2],
            "G1": roi[0::2, 1::2],
            "G2": roi[1::2, 0::2],
            "B": roi[1::2, 1::2],
        }
        stats = {
            name: {
                "mean": float(np.mean(plane)),
                "std": float(np.std(plane)),
                "p999": float(np.percentile(plane, 99.9)),
                "max": int(np.max(plane)),
            }
            for name, plane in planes.items()
        }
        exposure_s = float(metadata["ExposureTime"]) / 1e6
        return stats, exposure_s

    def _capture_batch(self, tier_us, frames):
        """Measured frames at a tier, transitional frames filtered out.

        Keeps only frames whose reported exposure matches the batch median
        within 1% — a clamped tier is fine (every frame reports the same
        clamped value), a transitional frame is not.
        """
        self._set_tier(tier_us)
        batch = [self._grab() for _ in range(frames + 1)]
        exposures = sorted(exposure for _, exposure in batch)
        median = exposures[len(exposures) // 2]
        kept = [item for item in batch if abs(item[1] - median) <= 0.01 * median]
        return kept[:frames], median

    def saturated(self, stats):
        return stats["R"]["p999"] >= SATURATION_FRACTION * self.full_scale

    def measure_dark_floors(self, frames=FRAMES_PER_MEASUREMENT):
        """Per-tier dark floors with the panel blanked. Run before anything.

        Also the enclosure-darkness gate: a light leak shows as R-plane dark
        signal growing with exposure far beyond dark current.
        """
        self.dark = {}
        for tier in self.tiers_us:
            batch, actual = self._capture_batch(tier, frames)
            self.dark[tier] = {
                "actual_exposure_s": actual,
                "planes": {
                    name: float(np.mean([stats[name]["mean"] for stats, _ in batch]))
                    for name in ("R", "G1", "G2", "B")
                },
            }
        return self.dark

    def flux(self, stats, exposure_s, tier_us):
        """Panel flux (ADU/s, top-tier scale) from one frame's R-plane mean."""
        dark = self.dark[tier_us]["planes"]["R"] if tier_us in self.dark else 0.0
        scale = self.tier_scale.get(tier_us, 1.0)
        return (stats["R"]["mean"] - dark) * scale / exposure_s

    def frames_for(self, tier_us, frames=None):
        """Frames to average at a tier: many on sub-period tiers (beat), few
        on period-locked ones."""
        if frames is not None:
            return frames
        if self.refresh_us is not None and tier_us < self.refresh_us:
            return SUB_PERIOD_FRAMES
        if self.refresh_us is None and tier_us <= SUB_PERIOD_TIER_US:
            return SUB_PERIOD_FRAMES
        return FRAMES_PER_MEASUREMENT

    def _record(self, tier, batch, actual, saturated):
        fluxes = [self.flux(stats, exposure, tier) for stats, exposure in batch]
        return {
            "tier_us": tier,
            "actual_exposure_s": actual,
            "gain": self.gain,
            "frames": len(batch),
            "flux": None if saturated else float(np.mean(fluxes)),
            "flux_std": None if saturated else float(np.std(fluxes)),
            "planes": batch[0][0],
            "saturated": saturated,
        }

    def measure(self, frames=None, tier_us=None):
        """One measurement at the best tier (or a forced one).

        Auto-ranging walks from the last used tier: shorter while any frame
        saturates, longer while the signal is weak, never revisiting a tier.
        If the walk dead-ends on saturation, the last unsaturated batch wins.
        ``flux`` is None only if every tried tier saturated (the shortest
        tier exists to prevent that).
        """
        if tier_us is not None:
            batch, actual = self._capture_batch(
                tier_us, self.frames_for(tier_us, frames)
            )
            saturated = any(self.saturated(stats) for stats, _ in batch)
            return self._record(tier_us, batch, actual, saturated)

        order = sorted(self.tiers_us, reverse=True)  # longest first
        index = order.index(self._current_tier) if self._current_tier in order else 0
        tried = set()
        fallback = None
        while True:
            tier = order[index]
            tried.add(tier)
            batch, actual = self._capture_batch(tier, self.frames_for(tier, frames))
            if any(self.saturated(stats) for stats, _ in batch):
                if index + 1 < len(order) and order[index + 1] not in tried:
                    index += 1
                    continue
                if fallback is not None:
                    return self._record(*fallback, saturated=False)
                return self._record(tier, batch, actual, saturated=True)
            fallback = (tier, batch, actual)
            dark = self.dark.get(tier, {}).get("planes", {}).get("R", 0.0)
            signal = batch[0][0]["R"]["mean"] - dark
            if signal < LOW_SIGNAL_ADU and index > 0 and order[index - 1] not in tried:
                index -= 1
                continue
            return self._record(tier, batch, actual, saturated=False)


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------


class Rig:
    """Lights + panel + photometer, brought up and torn down as one.

    Use as a context manager: entry douses stray lights, initialises the
    panel, measures dark floors and cross-calibrates the exposure ladder;
    exit restores LEDs and resets the panel.
    """

    def __init__(self, panel_name, tiers_us=None, journal_path=None, refresh_us=None):
        self.panel_name = panel_name
        self.tiers_us = tiers_us
        self.refresh_us_override = refresh_us
        self.journal_path = Path(journal_path) if journal_path else None
        self.lights = Lights()
        self.panel = None
        self.photometer = None
        self._seq = 0

    def __enter__(self):
        self.lights.douse()
        self.panel = PANELS[self.panel_name]()
        self.photometer = Photometer(tiers_us=self.tiers_us or [SUB_PERIOD_TIER_US])
        self.panel.blank()
        time.sleep(SETTLE_SECONDS)

        if self.tiers_us is None:
            refresh = self.refresh_us_override or self.measure_refresh()
            if refresh:
                self.photometer.refresh_us = refresh
                self.photometer.tiers_us = sorted(
                    {periods * refresh for periods in LADDER_PERIODS}
                    | {SUB_PERIOD_TIER_US},
                    reverse=True,
                )
            else:
                print("warning: no refresh null found; falling back to fixed tiers")
                self.photometer.tiers_us = sorted(DEFAULT_TIERS_US, reverse=True)
        self.journal(
            {
                "type": "rig",
                "camera": self.photometer.camera_type,
                "refresh_us": self.photometer.refresh_us,
                "tiers_us": self.photometer.tiers_us,
            }
        )

        self.panel.blank()
        time.sleep(SETTLE_SECONDS)
        self.photometer.measure_dark_floors()
        self.journal({"type": "dark_floors", "dark": self.photometer.dark})
        self.calibrate_ladder()
        return self

    # -- refresh -----------------------------------------------------------

    #: Coarse beat-scan bounds/step (µs), bracketing plausible panel refresh
    #: periods (~45-125 Hz).
    REFRESH_SCAN = (8_000, 22_000, 500)

    #: Candidate probe states for the scan, dimmest first: want the whole
    #: scan range unsaturated but with strong signal.
    _REFRESH_STATES = [
        {"contrast": 4, "master": 1},
        {"contrast": 4, "master": 3},
        {"contrast": 16, "master": 3},
        {"contrast": 64, "master": 7},
    ]

    def _beat_cv(self, tier_us, frames):
        """Frame-to-frame flux CV (%) at an exposure; None if any saturates.

        Uses a constant nominal bias instead of measured dark floors (which
        don't exist yet when this runs) — fine for locating a CV null.
        """
        batch, _ = self.photometer._capture_batch(tier_us, frames)
        if any(self.photometer.saturated(stats) for stats, _ in batch):
            return None
        fluxes = np.array(
            [(stats["R"]["mean"] - 240.0) / exposure for stats, exposure in batch]
        )
        return float(np.std(fluxes) / np.mean(fluxes) * 100)

    def measure_refresh(self):
        """Measures the panel's refresh period as the camera's beat null.

        Sub-period exposures sample the panel's PWM at random phase (~30%
        frame-to-frame CV); an exposure of exactly one refresh period
        integrates whole periods and the CV collapses (measured: 0.1%). The
        null's location is the period. Re-measured at every rig bring-up:
        the controller clock is an internal RC oscillator, so the period is
        per-panel and temperature-dependent.
        """
        lo, hi, step = self.REFRESH_SCAN
        max_exposure_s = hi / 1e6

        probe = None
        for state in self._REFRESH_STATES:
            self.panel.set_state(state, 255)
            time.sleep(SETTLE_SECONDS)
            batch, _ = self.photometer._capture_batch(SUB_PERIOD_TIER_US, 8)
            flux = float(np.mean([(s["R"]["mean"] - 240.0) / e for s, e in batch]))
            if flux * max_exposure_s < 0.75 * self.photometer.full_scale:
                probe = state
                if flux * max_exposure_s > 0.1 * self.photometer.full_scale:
                    break  # dim enough to scan, bright enough to resolve
        if probe is None:
            probe = self._REFRESH_STATES[0]
        self.panel.set_state(probe, 255)
        time.sleep(SETTLE_SECONDS)

        coarse = []
        for tier in range(lo, hi + 1, step):
            cv = self._beat_cv(tier, 6)
            if cv is None:
                break  # saturation; longer tiers only get worse
            coarse.append((tier, cv))
        if not coarse:
            return None

        centre = min(coarse, key=lambda item: item[1])[0]
        fine = []
        for tier in range(centre - 400, centre + 401, 100):
            cv = self._beat_cv(tier, 10)
            if cv is not None:
                fine.append((tier, cv))
        best_tier, best_cv = min(fine, key=lambda item: item[1])
        self.journal(
            {
                "type": "refresh",
                "probe_state": probe,
                "coarse": coarse,
                "fine": fine,
                "refresh_us": best_tier,
                "null_cv_pct": best_cv,
            }
        )
        if best_cv > 1.5:
            print(f"warning: weak refresh null (CV {best_cv:.2f}% at {best_tier}us)")
            return None
        print(f"refresh period: {best_tier}us (null CV {best_cv:.2f}%)")
        return best_tier

    def __exit__(self, *exc):
        if self.panel is not None:
            self.panel.reset()
        if self.photometer is not None:
            self.photometer.close()
        self.lights.restore()
        return False

    # -- ladder ------------------------------------------------------------

    #: Candidate panel states for tier cross-calibration, dimmest first.
    #: For each adjacent tier pair the first state that gives the longer tier
    #: an unsaturated frame and the shorter tier decent signal wins.
    _CAL_STATES = [
        {"contrast": 4, "master": 0},
        {"contrast": 16, "master": 3},
        {"contrast": 64, "master": 7},
        {"contrast": 160, "master": 15},
    ]

    def calibrate_ladder(self):
        """Chains empirical flux ratios so every tier reports on one scale.

        The longest tier anchors the scale at 1.0. For each adjacent pair,
        the same panel state is measured at both tiers and the ratio of raw
        (unscaled) fluxes becomes the shorter tier's correction, compounded
        down the ladder. If the sensor were perfectly linear and metadata
        exposures exact, every scale would be 1.0; the journal records how
        far reality is from that.
        """
        photometer = self.photometer
        photometer.tier_scale = {}
        tiers = sorted(photometer.tiers_us, reverse=True)
        scales = {tiers[0]: 1.0}
        records = []
        for longer, shorter in zip(tiers, tiers[1:]):
            pair = None
            for state in self._CAL_STATES:
                self.panel.set_state(state, 255)
                time.sleep(SETTLE_SECONDS)
                long_batch, _ = photometer._capture_batch(
                    longer, photometer.frames_for(longer)
                )
                if photometer.saturated(long_batch[0][0]):
                    continue
                short_batch, _ = photometer._capture_batch(
                    shorter, photometer.frames_for(shorter)
                )
                short_signal = (
                    short_batch[0][0]["R"]["mean"]
                    - photometer.dark[shorter]["planes"]["R"]
                )
                if short_signal < LOW_SIGNAL_ADU:
                    continue
                long_flux = np.mean(
                    [
                        (s["R"]["mean"] - photometer.dark[longer]["planes"]["R"]) / e
                        for s, e in long_batch
                    ]
                )
                short_flux = np.mean(
                    [
                        (s["R"]["mean"] - photometer.dark[shorter]["planes"]["R"]) / e
                        for s, e in short_batch
                    ]
                )
                pair = (state, float(long_flux), float(short_flux))
                break
            if pair is None:
                # No overlap state found; trust metadata for this joint.
                scales[shorter] = scales[longer]
                records.append({"longer": longer, "shorter": shorter, "ratio": None})
                continue
            state, long_flux, short_flux = pair
            ratio = long_flux / short_flux
            scales[shorter] = scales[longer] * ratio
            records.append(
                {
                    "longer": longer,
                    "shorter": shorter,
                    "state": state,
                    "long_flux": long_flux,
                    "short_flux": short_flux,
                    "ratio": ratio,
                }
            )
        photometer.tier_scale = scales
        self.panel.blank()
        self.journal({"type": "ladder", "scales": scales, "pairs": records})
        return records

    # -- measurement -------------------------------------------------------

    def measure_state(
        self,
        axis_values,
        pixel_value,
        frames=None,
        tier_us=None,
        record_type="measurement",
    ):
        """Programs a panel state, settles, measures, journals, returns."""
        self.panel.set_state(axis_values, pixel_value)
        time.sleep(SETTLE_SECONDS)
        result = self.photometer.measure(frames=frames, tier_us=tier_us)
        self._seq += 1
        record = {
            "type": record_type,
            "seq": self._seq,
            "time": time.time(),
            "panel": self.panel_name,
            "state": self.panel.state(),
            **result,
        }
        self.journal(record)
        return record

    def measure_sentinel(self, frames=None):
        """Fixed dim state re-measured; drift shows as sentinel flux moving."""
        return self.measure_state(
            self.panel.sentinel_axes, 255, frames=frames, record_type="sentinel"
        )

    def journal(self, record):
        if self.journal_path is None:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "a") as handle:
            handle.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _point_key(axes, value):
    return json.dumps({"axes": axes, "value": value}, sort_keys=True)


def run_sweep(rig, spec, resume_keys):
    pinned = spec.get("pinned", {})
    frames = spec.get("frames")  # None -> per-tier defaults
    sentinel_every = spec.get("sentinel_every", 25)
    points = spec["points"]

    done = 0
    for index, point in enumerate(points):
        axes = dict(pinned, **point.get("axes", {}))
        value = point.get("value", 255)
        # Resume keys are built from journaled full states, so complete the
        # point's axes with the panel references before comparing.
        full_state = dict(rig.panel.reference_state(), **axes)
        if _point_key(full_state, value) in resume_keys:
            continue
        if sentinel_every and done % sentinel_every == 0:
            rig.measure_sentinel(frames=frames)
        record = rig.measure_state(
            axes, value, frames=frames, tier_us=point.get("tier_us")
        )
        done += 1
        flux = record["flux"]
        flux_text = f"{flux:.4g} ADU/s" if flux is not None else "SATURATED"
        print(f"[{index + 1}/{len(points)}] {axes} value={value}: {flux_text}")
    if sentinel_every:
        rig.measure_sentinel(frames=frames)
    print(f"sweep complete: {done} new points, journal: {rig.journal_path}")


def run_monitor(panel_name, tier_us=100_000):
    """Live stray-light readout for physically hunting enclosure leaks.

    Douses the LEDs, blanks the panel, then prints one dark reading per
    second until interrupted — cover, drape and unplug things and watch the
    number respond. Skips the Rig's dark-floor/ladder bring-up so it starts
    fast, and estimates bias from a 1 ms frame (panel light and leaks are
    both negligible at 1 ms next to the working tier).
    """
    lights = Lights()
    lights.douse()
    panel = None
    try:
        panel = PANELS[panel_name]()
        panel.blank()
    except Exception as error:  # leak hunting must work with the lid open
        print(f"warning: panel unavailable ({error}); monitoring camera only")
    photometer = Photometer(tiers_us=[tier_us, 1_000])

    try:
        batch, _ = photometer._capture_batch(1_000, 2)
        bias = float(np.mean([stats["R"]["mean"] for stats, _ in batch]))
        print(
            f"bias ~{bias:.0f} ADU; monitoring at {tier_us}us "
            f"(Ctrl-C to stop, restores LEDs)"
        )
        print("goal: leak under ~10 ADU/s — dim-end panel signals are ~100 ADU/s")
        while True:
            batch, actual = photometer._capture_batch(tier_us, 1)
            mean = batch[0][0]["R"]["mean"]
            leak = (mean - bias) / actual
            bar = "#" * min(60, int(math.log10(max(leak, 1)) * 15)) if leak > 1 else ""
            print(f"  {mean:7.1f} ADU  leak {leak:9.1f} ADU/s  {bar}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        if panel is not None:
            panel.reset()
        photometer.close()
        lights.restore()
        print("\nmonitor stopped, LEDs restored")


def run_selftest(rig):
    """Proves the rig out end to end; prints a human-readable report."""
    photometer = rig.photometer
    report = ["", "=== panel photometry selftest ==="]
    report.append(f"camera: {photometer.camera_type}, gain {photometer.gain}")
    if photometer.refresh_us:
        report.append(f"panel refresh period: {photometer.refresh_us}us")
    else:
        report.append("panel refresh period: NOT FOUND — fixed fallback tiers")

    report.append("")
    report.append("dark floors (R-plane mean ADU):")
    tiers = sorted(photometer.dark)
    for tier in tiers:
        entry = photometer.dark[tier]
        saturated = entry["planes"]["R"] >= SATURATION_FRACTION * photometer.full_scale
        report.append(
            f"  tier {tier:>9}us (actual {entry['actual_exposure_s'] * 1e6:>9.0f}us): "
            f"R {entry['planes']['R']:8.2f}"
            + (
                "  SATURATED — tier unusable, so much leak it clips"
                if saturated
                else ""
            )
        )
    if len(tiers) >= 2:
        low, high = photometer.dark[min(tiers)], photometer.dark[max(tiers)]
        slope = (high["planes"]["R"] - low["planes"]["R"]) / (
            high["actual_exposure_s"] - low["actual_exposure_s"]
        )
        # A uniform, stable dark slope (dark current / pedestal, ~140 ADU/s
        # on this sensor) subtracts out per tier; only a large slope means
        # actual ambient light. Stability is gated separately at the end.
        report.append(f"  dark slope: {slope:.2f} ADU/s (dark current + any leak)")
        report.append(
            f"  darkness gate: {'PASS' if abs(slope) < 1000 else 'FAIL — ambient light'}"
        )

    report.append("")
    report.append("exposure ladder scales (1.0 = metadata exposures agree):")
    for tier, scale in sorted(photometer.tier_scale.items(), reverse=True):
        report.append(f"  tier {tier:>9}us: x{scale:.4f}")

    report.append("")
    report.append("repeatability (reference state, 5 measurements):")
    fluxes = [rig.measure_sentinel()["flux"] for _ in range(5)]
    mean = float(np.mean(fluxes))
    cv = float(np.std(fluxes) / mean * 100) if mean else float("nan")
    report.append(f"  flux {mean:.4g} ADU/s, CV {cv:.2f}%")
    report.append(f"  repeatability gate: {'PASS' if cv < 2.0 else 'FAIL — unstable'}")

    report.append("")
    report.append("range probe (dimmest vs brightest policy-reachable state):")
    dim_axes = {"contrast": 4, "master": 0}
    if rig.panel_name == "ssd1333":
        dim_axes.update({"ceiling": 4, "precharge": 8})
    dim = rig.measure_state(dim_axes, 255)
    bright_axes = {"contrast": 160, "master": 15}
    bright = rig.measure_state(bright_axes, 255)
    report.append(
        f"  dim    {dim_axes}: {dim['flux']:.4g} ADU/s (tier {dim['tier_us']}us)"
    )
    report.append(
        f"  bright {bright_axes}: {bright['flux']:.4g} ADU/s (tier {bright['tier_us']}us)"
    )
    if dim["flux"] and bright["flux"] and dim["flux"] > 0:
        span = bright["flux"] / dim["flux"]
        report.append(f"  span: {span:.0f}:1 ({math.log10(span):.1f} decades)")

    report.append("")
    report.append("dark-floor stability (start-of-run vs now, longest tier):")
    rig.panel.blank()
    time.sleep(SETTLE_SECONDS)
    top = max(photometer.dark)
    batch, _ = photometer._capture_batch(top, FRAMES_PER_MEASUREMENT)
    now = float(np.mean([stats["R"]["mean"] for stats, _ in batch]))
    initial = photometer.dark[top]["planes"]["R"]
    delta = now - initial
    limit = max(5.0, 0.01 * initial)
    report.append(
        f"  tier {top}us: was {initial:.2f}, now {now:.2f} ADU (delta {delta:+.2f})"
    )
    report.append(
        f"  stability gate: {'PASS' if abs(delta) <= limit else 'FAIL — dark is moving'}"
    )

    print("\n".join(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("command", choices=["selftest", "measure", "sweep", "monitor"])
    parser.add_argument("--panel", required=True, choices=sorted(PANELS))
    parser.add_argument("--axes", default="", help="e.g. contrast=64,master=7")
    parser.add_argument("--value", type=int, default=255, help="pixel value 0-255")
    parser.add_argument("--tier", type=int, default=None, help="force a tier (us)")
    parser.add_argument("--frames", type=int, default=FRAMES_PER_MEASUREMENT)
    parser.add_argument("--spec", help="sweep spec JSON path")
    parser.add_argument("--out", help="journal JSONL path")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--refresh-us",
        type=int,
        default=None,
        help="skip the refresh measurement and use this period (us)",
    )
    args = parser.parse_args()

    journal = args.out
    if journal is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        journal = MEASUREMENTS_DIR / args.panel / f"{args.command}-{stamp}.jsonl"

    resume_keys = set()
    if args.resume and Path(journal).exists():
        with open(journal) as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("type") == "measurement":
                    state = dict(record["state"])
                    value = state.pop("value")
                    resume_keys.add(_point_key(state, value))

    spec = None
    if args.command == "sweep":
        if not args.spec:
            parser.error("sweep requires --spec")
        with open(args.spec) as handle:
            spec = json.load(handle)

    if args.command == "monitor":
        run_monitor(args.panel, tier_us=args.tier or 100_000)
        return 0

    with Rig(args.panel, journal_path=journal, refresh_us=args.refresh_us) as rig:
        if args.command == "selftest":
            run_selftest(rig)
        elif args.command == "measure":
            axes = {}
            if args.axes:
                for pair in args.axes.split(","):
                    axis, _, value = pair.partition("=")
                    axes[axis.strip()] = int(value, 0)
            record = rig.measure_state(
                axes, args.value, frames=args.frames, tier_us=args.tier
            )
            print(json.dumps(record, indent=2))
        elif args.command == "sweep":
            run_sweep(rig, spec, resume_keys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
