"""
Profile SQM.calculate() and NoiseFloorEstimator.estimate_noise_floor() on a
synthetic but representative 512x512 frame.

The interesting questions:

  1. How long does one SQM.calculate() take? (Bounded budget: solver gates
     to once per 5 s, so anything <50 ms is invisible at the system level.
     Anything >500 ms could plausibly stall the single-core Pi via
     scheduler contention with the UI process.)
  2. Where does the time go inside calculate()? (per-star photometry loop
     vs noise-floor percentile vs sky-bg median vs the small numpy bits)
  3. How does cost scale with the number of matched stars (a realistic
     range is ~10-60 from tetra3 at our FOV).

This script does not import any UI / display / multiprocessing pieces, so
it can run anywhere with the PiFinder venv.

Run from python/ with venv activated:
    python profile_sqm.py
"""

from __future__ import annotations

import cProfile
import pstats
import statistics
import time
from io import StringIO

import numpy as np

from PiFinder.sqm import SQM as SQMCalculator


# ============================================================ helpers ===


def percentile(samples, p):
    if not samples:
        return float("nan")
    s = sorted(samples)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def bench(name, fn, iters=200, warmup=5):
    for _ in range(warmup):
        fn()
    samples_us = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples_us.append((time.perf_counter() - t0) * 1e6)
    samples_us.sort()
    print(
        f"  {name:<46s}  mean={statistics.mean(samples_us):10.1f} us  "
        f"median={statistics.median(samples_us):10.1f} us  "
        f"p95={percentile(samples_us, 95):10.1f} us  "
        f"max={samples_us[-1]:10.1f} us  (n={len(samples_us)})"
    )


# ============================================================ fixtures ===


def make_frame(rng, n_stars=30, fov_deg=12.0):
    """Build a 512x512 8-bit frame with sky background + N gaussian stars.

    Returns (image, solution_dict) suitable for SQM.calculate(...).
    """
    h, w = 512, 512
    # Sky background ~ ADU 30 with a few ADU of noise; mimics a Pi-camera
    # processed frame on a moderate-light-pollution sky.
    image = rng.normal(loc=30.0, scale=2.5, size=(h, w))

    # Stamp gaussian stars at random pixel positions, avoiding edges.
    margin = 20
    ys = rng.uniform(margin, h - margin, size=n_stars)
    xs = rng.uniform(margin, w - margin, size=n_stars)
    mags = rng.uniform(3.5, 9.0, size=n_stars)  # mix of bright + dim
    # Brighter stars get more ADU. peak_ADU = 200 * 10^(-0.4*(mag-3))
    peaks = 200.0 * np.power(10.0, -0.4 * (mags - 3.0))
    sigma = 1.3  # PSF stddev in pixels

    yy, xx = np.indices((h, w))
    for cy, cx, peak in zip(ys, xs, peaks):
        r2 = (yy - cy) ** 2 + (xx - cx) ** 2
        image += peak * np.exp(-r2 / (2 * sigma * sigma))

    image = np.clip(image, 0, 255).astype(np.uint8)

    # Matched centroids: tetra3 reports (y, x) order.
    matched_centroids = list(zip(ys.tolist(), xs.tolist()))
    # Matched stars triplet (ra, dec, mag) -- only mag is used in SQM.
    matched_stars = [(0.0, 0.0, float(m)) for m in mags]

    solution = {
        "FOV": fov_deg,
        "matched_centroids": matched_centroids,
        "matched_stars": matched_stars,
    }
    return image, solution


# ============================================================ main ===


def main():
    rng = np.random.default_rng(42)

    print("Profiling SQM.calculate() on synthetic 512x512 frames\n")

    # Construct one SQM instance, warm it up enough so the noise-floor
    # rolling median is in steady-state (>= 5 history samples).
    sqm = SQMCalculator(camera_type="imx296_processed")
    image_warmup, sol_warmup = make_frame(rng, n_stars=30)
    for _ in range(10):
        sqm.calculate(
            centroids=sol_warmup["matched_centroids"],
            solution=sol_warmup,
            image=image_warmup,
            exposure_sec=0.5,
            altitude_deg=45.0,
        )

    # 1. Cost as a function of matched-star count -----------------------------
    print("Cost vs matched-star count (3 frames per N, median reported):\n")
    for n in [10, 20, 30, 45, 60, 100]:
        frames = [make_frame(rng, n_stars=n) for _ in range(3)]

        def step(_frames=frames, _n=n):
            img, sol = _frames[step.i % len(_frames)]
            step.i += 1
            sqm.calculate(
                centroids=sol["matched_centroids"],
                solution=sol,
                image=img,
                exposure_sec=0.5,
                altitude_deg=45.0,
            )

        step.i = 0
        bench(f"calculate() with {n:3d} matched stars", step, iters=60)

    print()

    # 2. Sub-step breakdown at the canonical N=30 -----------------------------
    print("Sub-step breakdown at N=30 matched stars:\n")
    image, solution = make_frame(rng, n_stars=30)
    centroids_arr = np.array(solution["matched_centroids"])
    star_mags = [s[2] for s in solution["matched_stars"]]
    sqm._calc_field_parameters(solution["FOV"])

    def step_noise_floor():
        sqm.noise_estimator.estimate_noise_floor(image, 0.5, percentile=5.0)

    def step_per_star_photometry():
        sqm._measure_star_flux_with_local_background(
            image, centroids_arr, 5, 6, 14, 250
        )

    star_fluxes, local_bgs, _ = sqm._measure_star_flux_with_local_background(
        image, centroids_arr, 5, 6, 14, 250
    )

    def step_sky_bg_median():
        float(np.median(local_bgs))

    def step_mzero():
        sqm._calculate_mzero(star_fluxes, star_mags)

    def step_extinction():
        sqm._atmospheric_extinction(45.0)

    def step_full_calculate():
        sqm.calculate(
            centroids=solution["matched_centroids"],
            solution=solution,
            image=image,
            exposure_sec=0.5,
            altitude_deg=45.0,
        )

    bench("NoiseFloorEstimator.estimate_noise_floor", step_noise_floor)
    bench("per-star photometry loop (N=30)", step_per_star_photometry)
    bench("sky-bg median over local_backgrounds", step_sky_bg_median)
    bench("mzero (flux-weighted mean)", step_mzero)
    bench("extinction (Pickering airmass)", step_extinction)
    bench("calculate() full (composite)", step_full_calculate)

    # 3. cProfile of full calculate() at N=30 ----------------------------------
    print("\nFunction-level profile of calculate() at N=30 (top 20 by cumulative):\n")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(500):
        step_full_calculate()
    pr.disable()
    s = StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(20)
    for line in s.getvalue().splitlines():
        if line.strip():
            print(f"  {line}")

    # 4. Implied solver-process steady-state load -----------------------------
    print(
        "\nImplied steady-state load (SQM gated to one call per 5 s):\n"
    )
    # Read the canonical N=30 median back out by re-timing briefly.
    samples = []
    for _ in range(20):
        t0 = time.perf_counter()
        step_full_calculate()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    median_s = samples[len(samples) // 2]
    duty_pct = 100.0 * median_s / 5.0
    print(
        f"  calculate() median: {median_s * 1000:.1f} ms\n"
        f"  -> ~{duty_pct:.2f}% of one core in the solver process at steady state.\n"
        f"  (Plus ~{(median_s * 1000):.1f} ms of latency once every 5 s -- which on a\n"
        f"  single-core Pi can transiently delay the UI process during that window.)"
    )


if __name__ == "__main__":
    main()
