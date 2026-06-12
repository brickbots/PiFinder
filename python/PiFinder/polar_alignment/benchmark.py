"""
Monte Carlo accuracy benchmark for the polar alignment solver.

Exploratory accuracy comparison of the two-solve, three-solve-optimised, and
RA/Dec-only (cross-product) methods across a range of pointing geometries and
sweeps.  This is not a test -- the pass/fail correctness checks live in
tests/test_polar_alignment.py.  Run with

    python -m PiFinder.polar_alignment.benchmark

to print the comparison table.
"""

import logging
import platform as _platform
import time as _time

import numpy as np

from PiFinder.polar_alignment import get_platform_adjustments, make_solve_2

logger = logging.getLogger("PiFinder.polar_alignment.benchmark")


def main():
    observing_latitude = 51.2
    lst = 112.0  # degrees  (= 7h 28m sidereal time)

    dAlt_true = 1.5  # axis too high by 1.5°
    dAz_true = 3.0  # axis too far East by 3.0°

    sigma_ra = sigma_dec = 0.5 / 60  # 0.5 arcmin  (PiFinder/Tetra3 RA/Dec noise)
    sigma_roll = sigma_ra / np.radians(5.0)  # ≈11.46× sigma_ra  (1/R, R = 5° field)

    def _make_three_solves(ra1, dec1, roll1, sweep_total):
        """
        Return three plate solves for the given starting position and total sweep.
        Solve 1 is at 0°, solve 3 is at sweep_total°, and solve 2 is placed in
        the middle (sweep_total/2°) so the three solves span the full arc and the
        optimiser has the maximum geometric leverage.
        """
        ra2, dec2, roll2 = make_solve_2(
            ra1=ra1,
            dec1=dec1,
            roll1=roll1,
            latitude=observing_latitude,
            dAlt=dAlt_true,
            dAz=dAz_true,
            sweep_deg=sweep_total / 2,
            lst_deg=lst,
        )
        ra3, dec3, roll3 = make_solve_2(
            ra1=ra1,
            dec1=dec1,
            roll1=roll1,
            latitude=observing_latitude,
            dAlt=dAlt_true,
            dAz=dAz_true,
            sweep_deg=sweep_total,
            lst_deg=lst,
        )
        return ((ra1, dec1, roll1), (ra2, dec2, roll2), (ra3, dec3, roll3))

    def _mc_test(ra1, dec1, sweep_total, N=50):
        """
        Monte Carlo comparison of two-solve vs three-solve optimised vs
        RA/Dec-only (cross-product) for a given starting pointing and total sweep.
        Returns (mean2, p95_2, mean3, p95_3, mean_rd, p95_rd, t_per_call_3).
        """
        s1e, s2e, s3e = _make_three_solves(ra1, dec1, 0.0, sweep_total)

        rng = np.random.default_rng(42)
        e2, e3, erd, t3s, fqs, fqs_ir = [], [], [], [], [], []
        for _ in range(N):

            def noisy(s):
                return (
                    s[0] + rng.normal(0, sigma_ra),
                    s[1] + rng.normal(0, sigma_dec),
                    s[2] + rng.normal(0, sigma_roll),
                    0,
                )

            sn1, sn2, sn3 = noisy(s1e), noisy(s2e), noisy(s3e)

            def to_n(ar, ad):
                cd = np.cos(np.radians(ad))
                return np.array(
                    [
                        cd * np.cos(np.radians(ar)),
                        cd * np.sin(np.radians(ar)),
                        np.sin(np.radians(ad)),
                    ]
                )

            def aerr(n):
                return np.degrees(np.arccos(np.clip(np.dot(n, pax), -1, 1))) * 60

            # Two-solve
            _, _, _, ar, ad, _ = get_platform_adjustments(
                [sn1, sn2], observing_latitude, lst
            )
            if not np.isnan(ar):
                e2.append(aerr(to_n(ar, ad)))

            # Three-solve optimised — timed individually
            _t = _time.time()
            _, _, _, ar, ad, fq = get_platform_adjustments(
                [sn1, sn2, sn3],
                observing_latitude,
                lst,
                sigma_ra=sigma_ra,
                sigma_dec=sigma_dec,
                sigma_roll=sigma_roll,
            )
            t3s.append(_time.time() - _t)
            if not np.isnan(ar):
                e3.append(aerr(to_n(ar, ad)))
            if not np.isnan(fq):
                fqs.append(fq)

            # RA/Dec-only via ignore_roll=True
            _, _, _, ar, ad, fq_ir = get_platform_adjustments(
                [sn1, sn2, sn3],
                observing_latitude,
                lst,
                sigma_ra=sigma_ra,
                sigma_dec=sigma_dec,
                sigma_roll=sigma_roll,
                ignore_roll=True,
            )
            if not np.isnan(ar):
                erd.append(aerr(to_n(ar, ad)))
            if not np.isnan(fq_ir):
                fqs_ir.append(fq_ir)

        a2, a3, ard = np.array(e2), np.array(e3), np.array(erd)
        afq = np.array(fqs) if fqs else np.array([float("nan")])
        afq_ir = np.array(fqs_ir) if fqs_ir else np.array([float("nan")])
        return (
            np.mean(a2),
            np.percentile(a2, 95),
            np.mean(a3),
            np.percentile(a3, 95),
            np.mean(ard),
            np.percentile(ard, 95),
            np.mean(afq),
            np.percentile(afq, 95),
            np.mean(afq_ir),
            np.percentile(afq_ir, 95),
            np.mean(t3s),
        )

    # Build the true platform axis (needed to compute axis errors)
    lat_r = np.radians(observing_latitude)
    alt_ax = np.radians(observing_latitude + dAlt_true)
    az_ax = np.radians(dAz_true)
    dec_pax = np.arcsin(
        np.sin(lat_r) * np.sin(alt_ax) + np.cos(lat_r) * np.cos(alt_ax) * np.cos(az_ax)
    )
    ha_pax = np.arctan2(
        -np.cos(alt_ax) * np.sin(az_ax),
        np.cos(lat_r) * np.sin(alt_ax) - np.sin(lat_r) * np.cos(alt_ax) * np.cos(az_ax),
    )
    ra_pax = np.radians(lst) - ha_pax
    cd = np.cos(dec_pax)
    pax = np.array([cd * np.cos(ra_pax), cd * np.sin(ra_pax), np.sin(dec_pax)])

    # Monte Carlo comparison across four scenarios
    N_MC = 50
    logger.info(
        "Monte Carlo N=%d  sigma_RA/Dec=%.1f'  sigma_roll=%.1f'  (%.0fx)",
        N_MC,
        sigma_ra * 60,
        sigma_roll * 60,
        sigma_roll / sigma_ra,
    )
    logger.info(
        "Platform: %s  %s  Python %s",
        _platform.node(),
        _platform.processor() or _platform.machine(),
        _platform.python_version(),
    )
    logger.info("")
    hdr = (
        f"  {'Pointing':<18} {'Sweep':>7} | "
        f"{'2-solve':>8} {'p95':>7} | "
        f"{'3-solve opt':>11} {'p95':>7} | "
        f"{'RA/Dec only':>11} {'p95':>7} | "
        f"{'fq(3s)':>7} {'p95':>6} | "
        f"{'fq(ir)':>7} {'p95':>6} | {'3s t/call':>9}"
    )
    logger.info(hdr)
    logger.info("  " + "-" * (len(hdr) - 2))

    for label, (ra1, dec1) in [
        ("Dec=30° (far)", (180.0, 30.0)),
        ("Dec=45°", (180.0, 45.0)),
        ("Dec=70°", (180.0, 70.0)),
        ("Polaris (near)", (37.95, 89.26)),
    ]:
        for sweep in [14.0, 37.5, 90.0]:
            m2, p2, m3, p3, mrd, prd, mfq, pfq, mfq_ir, pfq_ir, dt = _mc_test(
                ra1, dec1, sweep, N=N_MC
            )
            logger.info(
                f"  {label:<18} {sweep:>6.0f}° | "
                f"{m2:>7.2f}' {p2:>6.2f}' | "
                f"{m3:>10.2f}' {p3:>6.2f}' | "
                f"{mrd:>10.2f}' {prd:>6.2f}' | "
                f"{mfq:>6.2f}  {pfq:>5.2f} | "
                f"{mfq_ir:>6.2f}  {pfq_ir:>5.2f} | {dt:>8.3f}s"
            )
        logger.info("")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
