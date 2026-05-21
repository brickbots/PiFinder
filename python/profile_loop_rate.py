"""
Measure the achievable main-loop rate (and therefore chart refresh rate)
with the new sleep_for_framerate throttle vs the old time.sleep(0.1).

Simulates one main-loop iteration as:
    1. The chart-equivalent render work (a full plot_starfield + composite)
    2. The throttle (sleep_for_framerate awake = 1/30s, or time.sleep(0.1))

Measures effective Hz over a 3-second window for each variant.

Run from python/ with venv activated:
    python profile_loop_rate.py
"""

from __future__ import annotations

import time
import types
from typing import Callable

import numpy as np
from PIL import Image, ImageChops

from PiFinder import plot
from PiFinder.displays import Colors, RED_RGB
from PiFinder.state_utils import sleep_for_framerate


RESOLUTION = (128, 128)
FOV = 10.2
DURATION_SEC = 3.0


def make_render_step() -> Callable[[], None]:
    """Build a closure that performs one chart render -- same work as
    UIChart.update() does on a successful per-frame path."""
    colors = Colors(RED_RGB, RESOLUTION)
    sf = plot.Starfield(colors, RESOLUTION, fov=FOV)
    screen = Image.new("RGB", RESOLUTION)
    base_ra, base_dec = 83.633, 22.0145
    rng = np.random.default_rng(42)

    state = {"i": 0}

    def step() -> None:
        # Small drift each frame, mirrors IMU-dead-reckoning publishes.
        ra = base_ra + float(rng.normal(0, 0.01))
        dec = base_dec + float(rng.normal(0, 0.01))
        roll = float(rng.uniform(-180, 180))
        image_obj, _vs = sf.plot_starfield(ra, dec, roll, 64)
        image_obj = ImageChops.multiply(image_obj.convert("RGB"), colors.red_image)
        screen.paste(image_obj)
        state["i"] += 1

    return step


def measure_rate(name: str, throttle: Callable[[], None], render: Callable[[], None]) -> None:
    # Warm up
    for _ in range(5):
        render()

    iters = 0
    start = time.perf_counter()
    deadline = start + DURATION_SEC
    while time.perf_counter() < deadline:
        render()
        throttle()
        iters += 1
    elapsed = time.perf_counter() - start
    hz = iters / elapsed
    print(
        f"  {name:<38s}  {iters:5d} iters in {elapsed:.2f}s  ->  {hz:5.1f} Hz "
        f"(period {1000 / hz:5.1f} ms)"
    )


def main() -> None:
    print(f"Measuring main-loop rate with chart render at {RESOLUTION}, FOV {FOV}\n")
    render = make_render_step()
    # Stub shared_state for sleep_for_framerate (only power_state() is read).
    awake_state = types.SimpleNamespace(power_state=lambda: 1)
    sleep_state = types.SimpleNamespace(power_state=lambda: 0)

    print("Chart-render iteration (real plot_starfield + composite):")
    measure_rate("BEFORE: time.sleep(0.1)", lambda: time.sleep(0.1), render)
    measure_rate(
        "AFTER (awake): sleep_for_framerate", lambda: sleep_for_framerate(awake_state), render
    )
    measure_rate(
        "AFTER (asleep): sleep_for_framerate",
        lambda: sleep_for_framerate(sleep_state),
        render,
    )

    # Menu screen simulation: render is near-zero work; the question is whether
    # we double-sleep (legacy: module's update() also called sleep_for_framerate
    # on top of the main loop) or single-sleep (after the menu-sleep audit).
    def menu_render() -> None:
        # ~A few hundred microseconds of work, mirroring text rendering.
        for _ in range(50):
            pass

    print("\nMenu-screen iteration (trivial render):")
    # Pre-audit: main loop sleeps (1/30s) AND the menu's update() also sleeps.
    def double_sleep() -> None:
        sleep_for_framerate(awake_state)  # the per-module sleep we removed
        sleep_for_framerate(awake_state)  # the main-loop sleep

    measure_rate(
        "BEFORE menu audit: sleep_for_framerate x2",
        double_sleep,
        menu_render,
    )
    measure_rate(
        "AFTER  menu audit: sleep_for_framerate x1",
        lambda: sleep_for_framerate(awake_state),
        menu_render,
    )

    print(
        "\nNote: AFTER (asleep) replaces the old 0.1s loop sleep + 0.2s PowerManager sleep (~3.3 Hz)\n"
        "with sleep_for_framerate's 0.5s sleep, i.e. ~2 Hz when asleep -- more power saving."
    )


if __name__ == "__main__":
    main()
