"""
Profile per-frame cost of PiFinder.ui.chart.UIChart.update().

We don't construct UIChart directly (too many deps); instead we exercise
the work UIChart.update() does on every frame -- the PiFinder.plot.Starfield
calls and the post-processing on the resulting image.

Sections:
  1. Starfield.update_projection      (skyfield observe + stereographic build)
  2. Starfield.plot_starfield total   (projection + render)
  3. Sub-steps of plot_starfield      (each pandas/projection block)
  4. The post-render compositing      (convert("RGB") + ImageChops.multiply)
  5. Starfield.plot_markers           (a few catalog markers)
  6. Composite per-frame total        (matches what update() does)

Also runs cProfile on the per-frame composite so we can spot non-obvious hot
spots in third-party code (pandas/skyfield/PIL).

Run from python/ with venv activated:
    python profile_chart.py [N]
"""

from __future__ import annotations

import cProfile
import pstats
import statistics
import sys
import time
from io import StringIO

import numpy as np
from PIL import Image, ImageChops
from skyfield.api import Angle

from PiFinder import plot
from PiFinder.displays import Colors, RED_RGB


RESOLUTION = (128, 128)
FOV = 10.2


def percentile(samples, p):
    if not samples:
        return float("nan")
    s = sorted(samples)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def bench(name, fn, iters=200, warmup=10):
    for _ in range(warmup):
        fn()
    samples_us = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples_us.append((time.perf_counter() - t0) * 1e6)
    samples_us.sort()
    mean = statistics.mean(samples_us)
    median = statistics.median(samples_us)
    p95 = percentile(samples_us, 95)
    p99 = percentile(samples_us, 99)
    mx = samples_us[-1]
    print(
        f"  {name:<42s}  "
        f"mean={mean:9.1f} us  median={median:9.1f} us  "
        f"p95={p95:9.1f} us  p99={p99:9.1f} us  "
        f"max={mx:10.1f} us  (n={len(samples_us)})"
    )
    return median


def make_starfield():
    colors = Colors(RED_RGB, RESOLUTION)
    sf = plot.Starfield(colors, RESOLUTION, fov=FOV)
    return sf, colors


def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 200

    print(f"Building Starfield (resolution={RESOLUTION}, fov={FOV})...")
    t0 = time.perf_counter()
    sf, colors = make_starfield()
    print(f"  Starfield init: {(time.perf_counter() - t0) * 1000:.1f} ms")
    print(f"  Bright stars loaded: {len(sf.stars)}")
    # Number of const edges == length of the start-star positions array.
    n_edges = len(sf.const_start_star_positions.position.km[0])
    print(f"  Constellation edges: {n_edges}")
    print()

    # Representative pointing positions -- a small drift each frame to simulate
    # IMU dead-reckoning between plate solves.
    rng = np.random.default_rng(42)
    base_ra, base_dec = 83.633, 22.0145  # near Orion
    pointings = [
        (
            base_ra + float(rng.normal(0, 0.01)),  # ~0.01 deg drift
            base_dec + float(rng.normal(0, 0.01)),
            float(rng.uniform(-180, 180)),  # roll
        )
        for _ in range(iters + 50)
    ]
    idx = {"i": 0}

    def next_pointing():
        p = pointings[idx["i"] % len(pointings)]
        idx["i"] += 1
        return p

    # ============================================================ 1. update_projection
    def step_update_projection():
        ra, dec, _roll = next_pointing()
        sf.update_projection(ra, dec)

    # ============================================================ 2. plot_starfield total
    def step_plot_starfield():
        ra, dec, roll = next_pointing()
        sf.plot_starfield(ra, dec, roll, constellation_brightness=64)

    # ============================================================ 3. sub-steps
    # Prime the projection so sub-step timings start from a valid state.
    sf.update_projection(base_ra, base_dec)
    sf.roll = 0.0

    def step_project_stars():
        sf._stars_x, sf._stars_y = sf.projection(sf.star_positions)

    def step_project_const():
        sf._const_sx, sf._const_sy = sf.projection(sf.const_start_star_positions)
        sf._const_ex, sf._const_ey = sf.projection(sf.const_end_star_positions)

    def step_render_pil():
        sf.render_starfield_pil(constellation_brightness=64)

    # ============================================================ 4. compositing
    # Mimic the UIChart.update() compositing: convert L -> RGB, multiply red mask.
    pre_image, _ = sf.plot_starfield(base_ra, base_dec, 0.0, 64)

    def step_convert_rgb():
        pre_image.convert("RGB")

    rgb_image = pre_image.convert("RGB")

    def step_multiply_red():
        ImageChops.multiply(rgb_image, colors.red_image)

    def step_full_compositing():
        rgb = pre_image.convert("RGB")
        ImageChops.multiply(rgb, colors.red_image)

    # ============================================================ 5. plot_markers
    marker_list = [
        (Angle(degrees=83.633)._hours, 22.0145, "target"),
        (Angle(degrees=88.79)._hours, 7.41, "galaxy"),
        (Angle(degrees=82.0)._hours, 23.0, "neb"),
    ]

    def step_plot_markers():
        sf.plot_markers(marker_list)

    # ============================================================ 6. full per-frame
    screen = Image.new("RGB", RESOLUTION)

    def step_full_frame():
        ra, dec, roll = next_pointing()
        image_obj, _vs = sf.plot_starfield(ra, dec, roll, 64)
        image_obj = ImageChops.multiply(image_obj.convert("RGB"), colors.red_image)
        screen.paste(image_obj)
        marker_image = sf.plot_markers(marker_list)
        marker_image = ImageChops.multiply(
            marker_image,
            Image.new("RGB", RESOLUTION, colors.get(128)),
        )
        screen.paste(ImageChops.add(screen, marker_image))

    # ============================================================ run
    print("Per-step timings (microseconds):\n")
    print(" -- skyfield projection setup --")
    bench("update_projection (per frame)", step_update_projection, iters)
    print()
    print(" -- star/constellation projection (per frame) --")
    bench("project stars (sf.projection)", step_project_stars, iters)
    bench("project constellation start+end", step_project_const, iters)
    print()
    print(" -- raster render (per frame) --")
    bench("render_starfield_pil", step_render_pil, iters)
    print()
    print(" -- compositing --")
    bench("Image.convert('L'->'RGB')", step_convert_rgb, iters)
    bench("ImageChops.multiply (red tint)", step_multiply_red, iters)
    bench("convert + multiply (composite)", step_full_compositing, iters)
    print()
    print(" -- markers --")
    bench("plot_markers (3 markers)", step_plot_markers, iters)
    print()
    print(" -- full per-frame --")
    bench("plot_starfield total", step_plot_starfield, iters)
    bench("full chart frame", step_full_frame, iters)

    # cProfile the full per-frame for function-level hotspots.
    print("\nFunction-level profile of full chart frame (top 20 by cumulative):\n")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(200):
        step_full_frame()
    pr.disable()
    s = StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(20)
    # Filter out the bench harness lines and trim noisy prefixes.
    out = s.getvalue()
    for line in out.splitlines():
        if line.strip():
            print(f"  {line}")


if __name__ == "__main__":
    main()
