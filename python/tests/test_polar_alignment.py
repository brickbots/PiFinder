"""
Tests for the polar-alignment-from-plate-solves module
(PiFinder.polar_alignment).

Covers:
- attitude matrix construction / extraction round trips
- two-solve exact recovery of dAlt/dAz/sweep in both hemispheres
- three-solve optimiser recovery, with and without noise
- ignore_roll (RA/Dec-only) path and its immunity to camera flop
- sweep sign conventions and the sidereal drift correction
- MIN_SWEEP_DEG degenerate handling
- precession (skyfield TETE) accuracy
- correction_target geometry
- degenerate inputs: 180° sweep, collinear boresights, out-of-order solves
"""

import numpy as np
import pytest

from PiFinder.polar_alignment import (
    MIN_SWEEP_DEG,
    attitude_mat,
    axis_to_altaz_error,
    correction_target,
    extract_plate_solve,
    get_platform_adjustments,
    make_solve_2,
    _precession_matrix,
    _SKYFIELD_TETE_FRAME,
)
from PiFinder.calc_utils import sf_utils

LAT_NH = 51.2
LAT_SH = -34.0
LST = 112.0
SIDEREAL_DEG_PER_SEC = 360.0 / 86164.09


def _axis_vec(ra_deg, dec_deg):
    cd = np.cos(np.radians(dec_deg))
    return np.array(
        [
            cd * np.cos(np.radians(ra_deg)),
            cd * np.sin(np.radians(ra_deg)),
            np.sin(np.radians(dec_deg)),
        ]
    )


def _true_axis(latitude, dAlt, dAz, lst_deg):
    """Equatorial unit vector of the pole-end of a misaligned axis."""
    lat = np.radians(latitude)
    if latitude >= 0:
        alt = np.radians(latitude + dAlt)
        az = np.radians(dAz)
    else:
        alt = np.radians(abs(latitude) + dAlt)
        az = np.radians(180.0 + dAz)
    dec = np.arcsin(np.sin(lat) * np.sin(alt) + np.cos(lat) * np.cos(alt) * np.cos(az))
    ha = np.arctan2(
        -np.cos(alt) * np.sin(az),
        np.cos(lat) * np.sin(alt) - np.sin(lat) * np.cos(alt) * np.cos(az),
    )
    ra = np.radians(lst_deg) - ha
    cd = np.cos(dec)
    return np.array([cd * np.cos(ra), cd * np.sin(ra), np.sin(dec)])


def _three_solves(ra1, dec1, latitude, dAlt, dAz, sweep_total, lst_deg):
    s2 = make_solve_2(ra1, dec1, 0.0, latitude, dAlt, dAz, sweep_total / 2, lst_deg)
    s3 = make_solve_2(ra1, dec1, 0.0, latitude, dAlt, dAz, sweep_total, lst_deg)
    return [(ra1, dec1, 0.0, 0), (*s2, 0), (*s3, 0)]


@pytest.mark.unit
class TestAttitudeMatrix:
    def test_round_trip(self):
        rng = np.random.default_rng(1)
        for _ in range(50):
            ra = rng.uniform(0, 360)
            dec = rng.uniform(-85, 85)
            roll = rng.uniform(-180, 180)
            ra2, dec2, roll2 = extract_plate_solve(attitude_mat(ra, dec, roll))
            assert ra2 == pytest.approx(ra, abs=1e-9)
            assert dec2 == pytest.approx(dec, abs=1e-9)
            assert np.isclose((roll2 - roll + 180) % 360 - 180, 0, atol=1e-9)

    def test_boresight_column(self):
        M = attitude_mat(30.0, 40.0, 17.0)
        assert np.allclose(M[:, 2], _axis_vec(30.0, 40.0))

    def test_is_rotation(self):
        M = attitude_mat(123.0, -45.0, 67.0)
        assert np.allclose(M @ M.T, np.eye(3), atol=1e-12)
        assert np.linalg.det(M) == pytest.approx(1.0)


@pytest.mark.unit
class TestAxisToAltAzError:
    def test_perfect_axis_nh(self):
        dAlt, dAz = axis_to_altaz_error([0.0, 0.0, 1.0], LAT_NH, LST)
        assert dAlt == pytest.approx(0.0, abs=1e-9)
        assert dAz == pytest.approx(0.0, abs=1e-9)

    def test_perfect_axis_sh(self):
        # SH: the function flips to the S-end, which points at the SCP
        dAlt, dAz = axis_to_altaz_error([0.0, 0.0, 1.0], LAT_SH, LST)
        assert dAlt == pytest.approx(0.0, abs=1e-9)
        assert dAz == pytest.approx(0.0, abs=1e-9)

    def test_known_offset_round_trip(self):
        # axis_to_altaz_error expects the NCP-side (z >= 0) axis direction,
        # as produced by get_platform_adjustments; it flips internally for SH.
        for lat in (LAT_NH, LAT_SH):
            axis = _true_axis(lat, 1.5, 3.0, LST)
            if axis[2] < 0:
                axis = -axis
            dAlt, dAz = axis_to_altaz_error(axis, lat, LST)
            assert dAlt == pytest.approx(1.5, abs=1e-9)
            assert dAz == pytest.approx(3.0, abs=1e-9)


@pytest.mark.unit
class TestTwoSolve:
    @pytest.mark.parametrize(
        "lat,dec1",
        [(LAT_NH, 30.0), (LAT_NH, 80.0), (LAT_SH, -30.0), (0.0, 20.0)],
    )
    def test_exact_recovery(self, lat, dec1):
        s2 = make_solve_2(180.0, dec1, 0.0, lat, 1.5, 3.0, 14.0, LST)
        dAlt, dAz, sweep, _, _, fq = get_platform_adjustments(
            [(180.0, dec1, 0.0, 0), (*s2, 0)], lat, LST
        )
        assert dAlt == pytest.approx(1.5, abs=1e-6)
        assert dAz == pytest.approx(3.0, abs=1e-6)
        assert sweep == pytest.approx(14.0, abs=1e-6)
        assert np.isnan(fq)  # two-solve has no residual

    def test_negative_errors(self):
        s2 = make_solve_2(180.0, 30.0, 0.0, LAT_NH, -0.7, -2.1, 20.0, LST)
        dAlt, dAz, *_ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0), (*s2, 0)], LAT_NH, LST
        )
        assert dAlt == pytest.approx(-0.7, abs=1e-6)
        assert dAz == pytest.approx(-2.1, abs=1e-6)

    def test_boresight_at_axis_roll_only(self):
        # Pointing at the mechanical axis: RA/Dec fixed, only roll changes.
        axis = _true_axis(LAT_NH, 1.5, 3.0, LST)
        ra_pt = np.degrees(np.arctan2(axis[1], axis[0])) % 360
        dec_pt = np.degrees(np.arcsin(axis[2]))
        dAlt, dAz, sweep, *_ = get_platform_adjustments(
            [(ra_pt, dec_pt, 0.0, 0), (ra_pt, dec_pt, 14.0, 0)], LAT_NH, LST
        )
        assert dAlt == pytest.approx(1.5, abs=1e-6)
        assert dAz == pytest.approx(3.0, abs=1e-6)
        assert abs(sweep) == pytest.approx(14.0, abs=1e-6)

    def test_requires_two_solves(self):
        with pytest.raises(ValueError):
            get_platform_adjustments([(180.0, 30.0, 0.0, 0)], LAT_NH, LST)

    def test_min_sweep_returns_nan_axis(self):
        s2 = make_solve_2(180.0, 30.0, 0.0, LAT_NH, 1.5, 3.0, 1.0, LST)
        _, _, sweep, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0), (*s2, 0)], LAT_NH, LST
        )
        assert abs(sweep) < MIN_SWEEP_DEG
        assert abs(sweep) == pytest.approx(1.0, abs=1e-6)
        assert np.isnan(ax_ra) and np.isnan(ax_dec)


@pytest.mark.unit
class TestSiderealDriftCorrection:
    def test_perfect_tracking_sweep(self):
        # Identical solves 1h apart: the platform followed the stars, so the
        # mechanical sweep equals the sidereal angle and is positive.
        gap = 3600.0
        _, _, sweep, *_ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0.0), (180.0, 30.0, 0.0, gap)], LAT_NH, 0.0
        )
        assert sweep == pytest.approx(gap * SIDEREAL_DEG_PER_SEC, abs=1e-6)

    def test_stationary_platform_drifted_sky(self):
        # Object drifted by exactly the sidereal rate: platform did not move,
        # so there is no rotation information.
        gap = 3600.0
        ra2 = 180.0 + gap * SIDEREAL_DEG_PER_SEC
        _, _, sweep, ax_ra, *_ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0.0), (ra2, 30.0, 0.0, gap)], LAT_NH, 0.0
        )
        assert sweep == pytest.approx(0.0, abs=1e-6)
        assert np.isnan(ax_ra)


@pytest.mark.unit
class TestThreeSolve:
    @pytest.mark.parametrize("lat,dec1", [(LAT_NH, 30.0), (LAT_SH, -30.0)])
    def test_exact_recovery(self, lat, dec1):
        solves = _three_solves(180.0, dec1, lat, 1.5, 3.0, 14.0, LST)
        dAlt, dAz, _, _, _, fq = get_platform_adjustments(solves, lat, LST)
        assert dAlt == pytest.approx(1.5, abs=1e-5)
        assert dAz == pytest.approx(3.0, abs=1e-5)
        assert fq == pytest.approx(0.0, abs=1e-4)

    def test_noisy_recovery_beats_sigma(self):
        sigma_ra = sigma_dec = 0.5 / 60
        sigma_roll = sigma_ra / np.radians(5.0)
        solves = _three_solves(180.0, 45.0, LAT_NH, 1.5, 3.0, 37.5, LST)
        true_ax = _true_axis(LAT_NH, 1.5, 3.0, LST)
        rng = np.random.default_rng(7)
        errs, fqs = [], []
        for _ in range(15):
            noisy = [
                (
                    ra + rng.normal(0, sigma_ra),
                    dec + rng.normal(0, sigma_dec),
                    roll + rng.normal(0, sigma_roll),
                    t,
                )
                for ra, dec, roll, t in solves
            ]
            _, _, _, ax_ra, ax_dec, fq = get_platform_adjustments(
                noisy,
                LAT_NH,
                LST,
                sigma_ra=sigma_ra,
                sigma_dec=sigma_dec,
                sigma_roll=sigma_roll,
            )
            err = np.degrees(
                np.arccos(np.clip(np.dot(_axis_vec(ax_ra, ax_dec), true_ax), -1, 1))
            )
            errs.append(err * 60)
            fqs.append(fq)
        # axis recovered to a few arcminutes with 0.5' input noise
        assert np.mean(errs) < 8.0
        # fit quality consistent with pure noise (not a systematic error)
        assert np.mean(fqs) < 3.0

    def test_ignore_roll_exact(self):
        solves = _three_solves(180.0, 45.0, LAT_NH, 1.5, 3.0, 30.0, LST)
        dAlt, dAz, _, _, _, fq = get_platform_adjustments(
            solves, LAT_NH, LST, ignore_roll=True
        )
        assert dAlt == pytest.approx(1.5, abs=1e-6)
        assert dAz == pytest.approx(3.0, abs=1e-6)
        assert fq == pytest.approx(0.0, abs=1e-4)

    def test_camera_flop_detected_and_survivable(self):
        # A 2-degree systematic roll error on the last solve (camera flop):
        # ignore_roll recovers the axis exactly; the optimised path reports
        # a fit_quality far above the noise-only expectation.
        solves = _three_solves(180.0, 45.0, LAT_NH, 1.5, 3.0, 30.0, LST)
        ra3, dec3, roll3, t3 = solves[2]
        flopped = solves[:2] + [(ra3, dec3, roll3 + 2.0, t3)]

        dAlt, dAz, _, _, _, fq_ir = get_platform_adjustments(
            flopped, LAT_NH, LST, ignore_roll=True
        )
        assert dAlt == pytest.approx(1.5, abs=1e-6)
        assert dAz == pytest.approx(3.0, abs=1e-6)
        assert fq_ir > 3.0  # roll inconsistency clearly flagged

        _, _, _, _, _, fq_opt = get_platform_adjustments(flopped, LAT_NH, LST)
        assert fq_opt > 3.0


@pytest.mark.unit
class TestPrecession:
    def test_aldebaran_tete(self):
        # Skyfield ICRS -> true equator/equinox of date (TETE) at 2025.41.
        # Expected values cross-checked once against astropy; the FK5
        # mean-of-date (precession only) reference is RA=69.3451,
        # Dec=16.5596, and TETE adds ~8" of nutation at this epoch.
        P = _precession_matrix(2025.41)
        v = P @ _axis_vec(68.9802, 16.5093)
        ra = np.degrees(np.arctan2(v[1], v[0])) % 360
        dec = np.degrees(np.arcsin(v[2]))
        assert ra == pytest.approx(69.3452, abs=1 / 3600)
        assert dec == pytest.approx(16.5619, abs=1 / 3600)

    def test_near_identity_at_j2000(self):
        # TETE at J2000.0 differs from ICRS by nutation at that epoch
        # (~17" peak) plus the small frame bias — not exactly identity.
        P = _precession_matrix(2000.0)
        assert np.abs(P - np.eye(3)).max() < 2e-4

    def test_is_rotation(self):
        P = _precession_matrix(2026.4)
        assert np.allclose(P @ P.T, np.eye(3), atol=1e-12)

    def test_j2000_pole_axis_recovered_through_pipeline(self):
        # Both solves point at the J2000 pole (only roll changes), so the
        # mechanical axis IS the J2000 pole.  With observation_jyear the
        # function precesses to JNOW and must see the axis offset from the
        # true pole by exactly the precession amount.  Checked against the
        # Skyfield's TETE frame directly, so this exercises the full
        # solve -> precess -> axis -> alt/az pipeline and will fail if
        # _precession_matrix() is rewritten incorrectly.
        lat, lst_deg, sweep, jyear_c = 51.2, 0.0, 14.0, 2026.44
        dAlt, dAz, sw, ax_ra, _, _ = get_platform_adjustments(
            [(0.0, 90.0, 0.0, 0), (0.0, 90.0, sweep, 0)],
            lat,
            lst_deg,
            observation_jyear=jyear_c,
        )
        _ts_c = sf_utils.ts.J(jyear_c)
        _ncp = _SKYFIELD_TETE_FRAME.rotation_at(_ts_c) @ np.array([0.0, 0.0, 1.0])
        gt_ra_c = np.degrees(np.arctan2(_ncp[1], _ncp[0])) % 360
        gt_dec_c = np.degrees(np.arcsin(np.clip(_ncp[2], -1, 1)))
        exp_axis = _axis_vec(gt_ra_c, gt_dec_c)
        exp_dAlt, exp_dAz = axis_to_altaz_error(exp_axis, lat, lst_deg)
        exp_ax_ra = np.degrees(np.arctan2(exp_axis[1], exp_axis[0])) % 360
        assert dAlt == pytest.approx(exp_dAlt, abs=1 / 3600)
        assert dAz == pytest.approx(exp_dAz, abs=1 / 3600)
        assert sw == pytest.approx(sweep, abs=1e-6)
        # axis RA near the pole is in the gimbal zone — relaxed tolerance
        assert abs((ax_ra - exp_ax_ra + 180) % 360 - 180) < 10 / 3600


@pytest.mark.unit
class TestCorrectionTarget:
    def test_scope_at_axis_lands_on_pole(self):
        # Scope pointing at the mechanical axis; after the Alt/Az correction
        # the boresight must sit on the NCP (alt = latitude, az = 0).
        axis = _true_axis(LAT_NH, 1.5, 3.0, LST)
        ra_pt = np.degrees(np.arctan2(axis[1], axis[0])) % 360
        dec_pt = np.degrees(np.arcsin(axis[2]))
        _, _, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(ra_pt, dec_pt, 0.0, 0), (ra_pt, dec_pt, 14.0, 0)], LAT_NH, LST
        )
        _, dec_t, _ = correction_target(
            ax_ra, ax_dec, (ra_pt, dec_pt, 14.0), LAT_NH, LST
        )
        assert dec_t == pytest.approx(90.0, abs=1e-4)

    def test_far_from_axis_target_dec0(self):
        # Last solve at Dec=0 near the meridian: the alt bolt is a seesaw
        # (north down = south up), so the correct target's ALTITUDE RISES
        # when the axis must come DOWN. Coordinate addition gets the sign
        # wrong and fails this by ~3 deg; the minimal rotation fails by
        # the eps^2 residual.
        ra1, dec1, roll1 = LST, 0.0, 0.0
        ra2, dec2, roll2 = make_solve_2(ra1, dec1, roll1, LAT_NH, 1.5, 3.0, 14.0, LST)
        _, _, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(ra1, dec1, roll1, 0), (ra2, dec2, roll2, 0)], LAT_NH, LST
        )
        ra_t, dec_t, roll_t = correction_target(
            ax_ra, ax_dec, (ra2, dec2, roll2), LAT_NH, LST
        )
        assert ra_t == pytest.approx(100.338436, abs=1e-3)
        assert dec_t == pytest.approx(1.537097, abs=1e-3)
        assert roll_t == pytest.approx(-1.818094, abs=1e-3)

    def test_aligned_axis_is_identity(self):
        ra_t, dec_t, roll_t = correction_target(
            0.0, 90.0, (180.0, 30.0, 5.0), LAT_NH, LST
        )
        assert ra_t == pytest.approx(180.0, abs=1e-9)
        assert dec_t == pytest.approx(30.0, abs=1e-9)
        assert roll_t == pytest.approx(5.0, abs=1e-9)

    def test_antipodal_axis(self):
        # Axis pointing exactly at the SCP; the correction rotation must map
        # it to the NCP, carrying the boresight from dec=-30 to dec=+30.
        _, dec_t, _ = correction_target(0.0, -90.0, (180.0, -30.0, 0.0), LAT_NH, LST)
        assert dec_t == pytest.approx(30.0, abs=1e-6)

    def test_roll_survives_precession_round_trip(self):
        # With the axis already on the JNOW pole (axis_ra/axis_dec are JNOW
        # coordinates) the correction (in solar reference) is identity,
        # so the J2000 input must come back almost unchanged

        # correction_target now corrects the J2000 target for annual
        # aberration, (solar->earth reference frame)
        # which can wiggle Ra and Dec coordinates 20",
        # so we need to allow for 30" separation.

        # Note: the annual aberration correction can *severely* change
        # roll very close to the pole, it will stay under 20" with Dec < 45°

        ra_t, dec_t, roll_t = correction_target(
            0.0, 90.0, (180.0, 30.0, 45.0), LAT_NH, LST, observation_jyear=2026.44
        )
        sep_arcsec = (
            np.degrees(
                np.arccos(
                    np.clip(
                        np.dot(_axis_vec(ra_t, dec_t), _axis_vec(180.0, 30.0)), -1, 1
                    )
                )
            )
            * 3600
        )
        assert sep_arcsec < 30.0
        assert roll_t == pytest.approx(45.0, abs=20.0 / 3600)

    def test_scope_at_axis_sh_lands_on_scp(self):
        # SH mirror of test_scope_at_axis_lands_on_pole: the scope points at
        # the S-end of the mechanical axis (only roll changes between solves).
        # After the Alt/Az correction the boresight must sit on the SCP
        # (dec = -90), the pole-pointing end in the southern hemisphere.
        s_end = _true_axis(LAT_SH, 1.5, 3.0, LST)  # S-end (z < 0) in SH
        ra_pt = np.degrees(np.arctan2(s_end[1], s_end[0])) % 360
        dec_pt = np.degrees(np.arcsin(s_end[2]))
        _, _, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(ra_pt, dec_pt, 0.0, 0), (ra_pt, dec_pt, 14.0, 0)], LAT_SH, LST
        )
        _, dec_t, _ = correction_target(
            ax_ra, ax_dec, (ra_pt, dec_pt, 14.0), LAT_SH, LST
        )
        assert dec_t == pytest.approx(-90.0, abs=1e-4)

    def test_j2000_pole_axis_target_back_precessed(self):
        # Mechanical axis is the J2000 pole; with observation_jyear the
        # correction target (returned in J2000) must equal the JNOW NCP
        # expressed in J2000 — the JNOW pole back through the precession
        # matrix.  Use Skyfield's TETE frame directly so the expected value
        # is independent of _precession_matrix(). Compared by angular
        # separation since RA is meaningless
        # near the pole; tolerance relaxed for the gimbal zone.

        # 10th of June 2026, time of astropy extraction of TETE apparent pole
        jyear_c = 2026.4398009005236

        _, _, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(0.0, 90.0, 0.0, 0), (0.0, 90.0, 14.0, 0)],
            LAT_NH,
            LST,
            observation_jyear=jyear_c,
        )
        ra_t, dec_t, _ = correction_target(
            ax_ra, ax_dec, (0.0, 90.0, 14.0), LAT_NH, LST, observation_jyear=jyear_c
        )
        # Ground truth: TETE Dec=90° (JNOW NCP) expressed in ICRS/J2000,
        # recovered through astropy i.e. the JNOW *apparent* pole back-rotated
        # through the precession matrix.
        # We're pointing right to the pole, so the target needs to be
        # the apparent pole.
        # With sweeps further from the pole we need less correction
        gt_ra_c = 1.0848564758628065
        gt_dec_c = 89.85753549689021
        gt_vec_c = _axis_vec(gt_ra_c, gt_dec_c)

        # Near Dec=90° RA in degrees is not meaningful — compare by angular
        # separation
        t_vec_c = _axis_vec(ra_t, dec_t)
        sep_arcsec = (
            np.degrees(np.arccos(np.clip(np.dot(t_vec_c, gt_vec_c), -1, 1))) * 3600
        )
        assert sep_arcsec < 30.0


@pytest.mark.unit
class TestDegenerateInputs:
    def test_min_sweep_dalt_daz_nan(self):
        # Below MIN_SWEEP_DEG the axis is unreliable; dAlt/dAz must be nan,
        # never 0.0 (which would read as "perfectly aligned").
        s2 = make_solve_2(180.0, 30.0, 0.0, LAT_NH, 1.5, 3.0, 1.0, LST)
        dAlt, dAz, *_ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0), (*s2, 0)], LAT_NH, LST
        )
        assert np.isnan(dAlt) and np.isnan(dAz)

    def test_180_degree_sweep(self):
        # At exactly 180 degrees the antisymmetric part of the rotation
        # vanishes; the axis must be recovered from the symmetric part.
        s2 = make_solve_2(180.0, 30.0, 0.0, LAT_NH, 1.5, 3.0, 180.0, LST)
        dAlt, dAz, sweep, *_ = get_platform_adjustments(
            [(180.0, 30.0, 0.0, 0), (*s2, 0)], LAT_NH, LST
        )
        assert abs(sweep) == pytest.approx(180.0, abs=1e-6)
        assert dAlt == pytest.approx(1.5, abs=1e-6)
        assert dAz == pytest.approx(3.0, abs=1e-6)

    def test_ignore_roll_collinear_boresights_nan(self):
        # Scope pointing at the mechanical axis: all boresights identical, so
        # RA/Dec carry no rotation information.  With ignore_roll=True the
        # axis must come back nan rather than silently derived from roll.
        axis = _true_axis(LAT_NH, 1.5, 3.0, LST)
        ra_pt = np.degrees(np.arctan2(axis[1], axis[0])) % 360
        dec_pt = np.degrees(np.arcsin(axis[2]))
        solves = [
            (ra_pt, dec_pt, 0.0, 0),
            (ra_pt, dec_pt, 7.0, 0),
            (ra_pt, dec_pt, 14.0, 0),
        ]
        dAlt, dAz, sweep, ax_ra, ax_dec, _ = get_platform_adjustments(
            solves, LAT_NH, LST, ignore_roll=True
        )
        assert np.isnan(dAlt) and np.isnan(dAz)
        assert np.isnan(ax_ra) and np.isnan(ax_dec)
        assert abs(sweep) == pytest.approx(14.0, abs=1e-6)

    def test_out_of_order_solves_sorted(self):
        # Solves are sorted by timestamp internally, so a shuffled input
        # gives the same result as the chronological one.
        solves = _three_solves(180.0, 45.0, LAT_NH, 1.5, 3.0, 30.0, LST)
        timed = [
            (ra, dec, roll, t)
            for (ra, dec, roll, _), t in zip(solves, (0.0, 60.0, 120.0))
        ]
        expected = get_platform_adjustments(timed, LAT_NH, LST)
        shuffled = [timed[2], timed[0], timed[1]]
        result = get_platform_adjustments(shuffled, LAT_NH, LST)
        assert result == pytest.approx(expected, abs=1e-9)


@pytest.mark.unit
class TestCorrectionTargetSanity:
    """
    Validate that the dAlt/dAz reported by get_platform_adjustments are
    exactly the knob movements embodied by correction_target: applying the
    rotation recovered from the (last solve -> target) attitudes must put the
    reported axis on the celestial pole via an azimuth-then-altitude knob
    composition.

    The exact match only holds with observation_jyear=None.  With it set,
    correction_target aims the knobs at the annual-aberration-nudged
    (apparent) pole while get_platform_adjustments reports dAlt/dAz against
    the geometric pole, so the two deliberately disagree by up to ~20.5"
    (see test_aberration_nudge_offsets_target_pole).
    """

    @staticmethod
    def _altaz(v, lat_deg, lst_deg):
        """Ground-frame (alt, az) in degrees of an equatorial unit vector."""
        dec = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
        ra = np.degrees(np.arctan2(v[1], v[0]))
        ha = np.radians(lst_deg - ra)
        lat = np.radians(lat_deg)
        dec_r = np.radians(dec)
        sin_alt = np.sin(lat) * np.sin(dec_r) + np.cos(lat) * np.cos(dec_r) * np.cos(ha)
        alt = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))
        az = np.degrees(
            np.arctan2(
                -np.cos(dec_r) * np.sin(ha),
                np.cos(lat) * np.sin(dec_r) - np.sin(lat) * np.cos(dec_r) * np.cos(ha),
            )
        )
        return alt, az % 360.0

    def _check(self, latitude, dAlt_true, dAz_true):
        ra1, dec1, roll1 = 180.0, 40.0 if latitude >= 0 else -40.0, 10.0
        ra2, dec2, roll2 = make_solve_2(
            ra1, dec1, roll1, latitude, dAlt_true, dAz_true, 30.0, LST
        )
        dAlt, dAz, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(ra1, dec1, roll1, 0), (ra2, dec2, roll2, 0)], latitude, LST
        )
        assert dAlt == pytest.approx(dAlt_true, abs=1e-6)
        assert dAz == pytest.approx(dAz_true, abs=1e-6)

        ra_t, dec_t, roll_t = correction_target(
            ax_ra, ax_dec, (ra2, dec2, roll2), latitude, LST
        )

        # The physical correction rotation, recovered purely from the
        # public outputs of correction_target.
        S = attitude_mat(ra_t, dec_t, roll_t) @ attitude_mat(ra2, dec2, roll2).T

        # 1) It puts the reported axis exactly on the celestial pole
        #    (angular separation -- azimuth is ill-conditioned at the pole).
        axis = _axis_vec(ax_ra, ax_dec)
        pole = np.array([0.0, 0.0, 1.0 if latitude >= 0 else 1.0])
        sep = np.degrees(np.arccos(np.clip(np.dot(S @ axis, pole), -1.0, 1.0)))
        assert sep == pytest.approx(0.0, abs=1e-6)

        # 2) The pole-pointing end of the axis moves by exactly the reported
        #    knob amounts: altitude down by dAlt, azimuth back by dAz.
        pole_end = axis if latitude >= 0 else -axis
        alt_before, az_before = self._altaz(pole_end, latitude, LST)
        alt_after, az_after = self._altaz(S @ pole_end, latitude, LST)
        assert alt_before - alt_after == pytest.approx(dAlt, abs=1e-6)
        d_az_moved = (az_before - az_after + 180.0) % 360.0 - 180.0
        # Azimuth of the corrected (near-pole) axis is ill-conditioned:
        # extract/rebuild float noise is amplified by 1/sin(colatitude).
        assert d_az_moved == pytest.approx(dAz, abs=1e-4)

        # 3) Knob composition: the azimuth stage leaves the zenith fixed and
        #    the altitude pin then tilts it within the pole's vertical
        #    (north-south) plane — so the corrected zenith must stay in that
        #    plane.  A single minimal rotation axis->pole would generally
        #    move it sideways.
        phi = np.radians(latitude)
        lst = np.radians(LST)
        zen = np.array(
            [np.cos(phi) * np.cos(lst), np.cos(phi) * np.sin(lst), np.sin(phi)]
        )
        _, az_zen = self._altaz(S @ zen, latitude, LST)
        assert abs(np.sin(np.radians(az_zen))) == pytest.approx(0.0, abs=1e-6)

    def test_knobs_match_target_nh(self):
        self._check(LAT_NH, 1.5, 3.0)

    def test_knobs_match_target_nh_negative_errors(self):
        self._check(LAT_NH, -2.0, -1.25)

    def test_knobs_match_target_sh(self):
        self._check(LAT_SH, 1.5, 3.0)

    def test_knobs_match_target_sh_negative_errors(self):
        self._check(LAT_SH, -0.75, -2.5)

    def test_aberration_nudge_offsets_target_pole(self):
        # With observation_jyear set, correction_target aims the physical
        # knobs at the APPARENT pole (annual-aberration nudge), so the
        # rotation recovered from its output lands the reported axis close
        # to -- but deliberately NOT exactly on -- the geometric pole.  The
        # offset is the aberration displacement scaled by cos(theta),
        # bounded by the aberration constant (~20.5").
        jyear = 2026.44
        ra1, dec1, roll1 = 180.0, 40.0, 10.0
        ra2, dec2, roll2 = make_solve_2(ra1, dec1, roll1, LAT_NH, 1.5, 3.0, 30.0, LST)
        _, _, _, ax_ra, ax_dec, _ = get_platform_adjustments(
            [(ra1, dec1, roll1, 0), (ra2, dec2, roll2, 0)],
            LAT_NH,
            LST,
            observation_jyear=jyear,
        )
        ra_t, dec_t, roll_t = correction_target(
            ax_ra, ax_dec, (ra2, dec2, roll2), LAT_NH, LST, observation_jyear=jyear
        )

        # Both target and last_solve are J2000; the knob rotation acts in
        # JNOW, so conjugate the recovered rotation with the precession
        # matrix to express it there, where the axis (ax_ra/ax_dec) lives.
        P = _precession_matrix(jyear)
        S = (
            P
            @ (attitude_mat(ra_t, dec_t, roll_t) @ attitude_mat(ra2, dec2, roll2).T)
            @ P.T
        )
        landed = S @ _axis_vec(ax_ra, ax_dec)
        sep_arcsec = np.degrees(np.arccos(np.clip(landed[2], -1.0, 1.0))) * 3600.0
        assert 5.0 < sep_arcsec < 25.0
