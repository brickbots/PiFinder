"""
polar_alignment.py
==================
Determines polar-axis misalignment from two plate solves taken while an
equatorial platform rotates around its (possibly mis-pointed) mechanical axis.

Convention
----------
World coordinate frame: standard equatorial (ICRS-like)
  X  →  RA = 0°,  Dec = 0°
  Y  →  RA = 90°, Dec = 0°
  Z  →  North Celestial Pole  (Dec = +90°)

Attitude matrix M (3×3 rotation)
  M maps camera-frame axes to world-frame axes.
  Column 2 of M is the boresight unit vector pointing at (RA, Dec):
    M[:,2] = [cos(Dec)cos(RA),  cos(Dec)sin(RA),  sin(Dec)]
  Construction:  M = Rz(RA) · Ry(90° − Dec) · Rz(−roll)
  Extraction via direct element read-off — no gimbal-lock issues.

Why LST is required
-------------------
The rotation axis extracted from the two plate solves is a direction in the
equatorial frame, characterised by (Dec_axis, RA_axis).  Its angular distance
from the NCP (= 90° − Dec_axis) is the total misalignment magnitude.  But to
decompose that tilt into a physical altitude error and an
azimuth error, we need to know which way is "North" on the ground
relative to the equatorial frame at the moment of the solves — that is exactly
what the Local Sidereal Time (LST) encodes:

    Hour Angle of axis  =  LST  −  RA_axis

Without LST, the RA of the axis is known but its azimuth on the ground is not.

Alt/Az sign convention
  dAlt > 0  →  axis pointing too high  (lower front of wedge / tilt head down)
  dAlt < 0  →  axis pointing too low   (raise front of wedge / tilt head up)
  dAlt/dAz describe the pole-pointing end of the axis (N-end in NH, S-end in SH).
  dAz  > 0  →  pole-end too far East (rotate wedge clockwise to correct)
  dAz  < 0  →  pole-end too far West (rotate wedge anticlockwise to correct)
  Azimuth is measured from North, positive toward East.
"""

import numpy as np
from scipy.spatial.transform import Rotation as R
from scipy.optimize import minimize
from skyfield.api import load as _skyfield_load
from skyfield.framelib import (
    true_equator_and_equinox_of_date as _SKYFIELD_TETE_FRAME,
)

# Minimum angular sweep between the first and last solve for a valid result.
# If the recovered sweep is below this threshold, the solves are too close
# together to reliably determine the axis direction, and (nan, nan) is
# returned for the axis quantities.  The sweep itself is still returned so
# the caller can report it to the user and ask for more platform rotation.
MIN_SWEEP_DEG = 3.0

_SKYFIELD_TS = _skyfield_load.timescale(builtin=True)  # bundled, no internet


# ── Low-level rotation helpers ────────────────────────────────────────────────

def _Rz(deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

def _Ry(deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


# ── Precession ───────────────────────────────────────────────────────────────

def _precession_matrix(jyear):
    """
    Rotation matrix from ICRS/J2000.0 to the true equator and equinox of
    date (TETE) at Julian year `jyear`, incorporating both precession and
    nutation (peak nutation amplitude ~17"), via skyfield (already a
    PiFinder dependency).
    """
    return _SKYFIELD_TETE_FRAME.rotation_at(_SKYFIELD_TS.J(jyear))


# ── Attitude matrix ───────────────────────────────────────────────────────────

def attitude_mat(ra_deg, dec_deg, roll_deg):
    """
    Build the 3×3 attitude matrix from a plate-solve result.

    M = Rz(RA) · Ry(90° − Dec) · Rz(−roll)

    Column 2 of M is the boresight unit vector:
      M[:,2] = [cos(Dec)cos(RA), cos(Dec)sin(RA), sin(Dec)]
    NCP = +Z axis.
    """
    return _Rz(ra_deg) @ _Ry(90.0 - dec_deg) @ _Rz(-roll_deg)


def extract_plate_solve(M):
    """
    Recover (RA, Dec, roll) from an attitude matrix.

    Uses direct element read-off — no gimbal-lock issues away from Dec = ±90°.
    """
    dec  = np.degrees(np.arcsin(np.clip(M[2, 2], -1.0, 1.0)))
    ra   = np.degrees(np.arctan2(M[1, 2], M[0, 2])) % 360.0
    roll = np.degrees(np.arctan2(-M[2, 1], -M[2, 0]))
    return ra, dec, roll


# ── Axis ↔ Alt/Az conversions ─────────────────────────────────────────────────

def axis_to_altaz_error(axis, latitude_deg, lst_deg):
    """
    Convert an equatorial unit-vector rotation axis to physical mount errors.

    A perfect polar axis points at the NCP = [0, 0, 1].  A mis-pointed axis
    has a small tilt away from that, which we express as how much the observer
    needs to move their altitude and azimuth adjusters to correct the error.

    LST is required because the azimuth of the axis on the ground depends on
    which RA is currently transiting the meridian:
        HA_axis = LST − RA_axis

    Parameters
    ----------
    axis         : array-like (3,)  Unit vector in equatorial frame (NCP = Z).
    latitude_deg : float            Observer's geographic latitude in degrees.
    lst_deg      : float            Local Sidereal Time in degrees (0–360).
                                    1 hour of time = 15 degrees.

    Returns
    -------
    dAlt : float  Altitude error in degrees.
    dAz  : float  Azimuth error in degrees (positive = East of North).
    """
    # In the SH, report the S-end of the axis (pointing toward SCP) so
    # that dAlt/dAz describe the pole-pointing end in both hemispheres.
    if latitude_deg < 0:
        axis = -np.asarray(axis, dtype=float)

    dec_ax = np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0)))
    ra_ax  = np.degrees(np.arctan2(axis[1], axis[0]))
    ha_ax  = lst_deg - ra_ax          # HA = LST − RA  (the key step)

    lat = np.radians(latitude_deg)
    dec = np.radians(dec_ax)
    ha  = np.radians(ha_ax)

    # Standard equatorial → horizontal transformation
    sin_alt = (np.sin(lat) * np.sin(dec)
               + np.cos(lat) * np.cos(dec) * np.cos(ha))
    alt = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))

    az = np.degrees(np.arctan2(
        -np.cos(dec) * np.sin(ha),
         np.cos(lat) * np.sin(dec) - np.sin(lat) * np.cos(dec) * np.cos(ha)))

    if latitude_deg >= 0:
        # NH: pole-pointing end is the N-end; reference is NCP (due North)
        dAlt = alt - latitude_deg
        dAz  = az
    else:
        # SH: pole-pointing end is the S-end; reference is SCP (due South)
        dAlt = alt - abs(latitude_deg)
        dAz  = az - 180.0
        if dAz >  180: dAz -= 360
        if dAz < -180: dAz += 360

    return dAlt, dAz


def correction_target(axis_ra, axis_dec, last_solve, observation_jyear=None):
    """
    Compute the J2000 coordinates the user must centre after applying the
    polar-axis correction.

    When the user tweaks the mount's Alt and Az adjusters to move the
    mechanical axis onto the celestial pole, the scope boresight shifts by
    the same rotation Q that maps the current (misaligned) axis onto the NCP.
    This function applies Q to the last plate-solve attitude and returns the
    resulting boresight in J2000/ICRS, ready to hand to a plate solver.

    The user does NOT move the RA/Dec axes of the mount — only Alt/Az.
    The scope therefore ends up pointing at a different sky position, and
    this function tells the plate solver what to expect.

    Parameters
    ----------
    axis_ra    : float  RA of the recovered mechanical axis in degrees (JNOW).
    axis_dec   : float  Dec of the recovered mechanical axis in degrees (JNOW).
    last_solve : tuple  (ra, dec, roll) of the last plate solve in degrees,
                        in the same coordinate system that was passed to
                        get_platform_adjustments() — i.e. J2000/ICRS if
                        observation_jyear is provided, otherwise JNOW.
    observation_jyear : float or None
                        Julian year of the observation, matching the value
                        passed to get_platform_adjustments().  When provided,
                        last_solve is treated as J2000/ICRS and precessed to
                        JNOW internally, and the returned target is J2000/ICRS.
                        If None (default), last_solve is assumed JNOW and the
                        returned target is also JNOW.

    Returns
    -------
    ra_target  : float  RA  of the correction target in degrees (J2000/ICRS if
                        observation_jyear given, else JNOW).
    dec_target : float  Dec of the correction target in degrees.
    roll_target: float  Expected roll at the target in degrees.
    """
    # Build the current axis unit vector (JNOW)
    cd   = np.cos(np.radians(axis_dec))
    axis = np.array([cd * np.cos(np.radians(axis_ra)),
                     cd * np.sin(np.radians(axis_ra)),
                     np.sin(np.radians(axis_dec))])

    # Precess last_solve from J2000/ICRS to JNOW so it matches the axis frame.
    ra_ls, dec_ls, roll_ls = last_solve[0], last_solve[1], last_solve[2]
    if observation_jyear is not None:
        P = _precession_matrix(observation_jyear)
        ra_ls, dec_ls, roll_ls = extract_plate_solve(
            P @ attitude_mat(ra_ls, dec_ls, roll_ls))

    # Rotation Q that maps axis -> NCP [0,0,1]
    ncp       = np.array([0., 0., 1.])
    cos_angle = np.clip(np.dot(axis, ncp), -1.0, 1.0)
    if abs(cos_angle - 1.0) < 1e-12:
        Q = np.eye(3)
    elif abs(cos_angle + 1.0) < 1e-12:
        # Antipodal: any 180° rotation about an axis in the xy-plane maps
        # -Z onto +Z (a rotation about Z would leave -Z where it is).
        Q = _Ry(180.0)
    else:
        rot_axis = np.cross(axis, ncp)
        rot_axis /= np.linalg.norm(rot_axis)
        Q = R.from_rotvec(np.arccos(cos_angle) * rot_axis).as_matrix()

    # Apply Q to the last-solve attitude matrix (JNOW)
    M_last      = attitude_mat(ra_ls, dec_ls, roll_ls)
    M_corrected = Q @ M_last

    # Precess back to J2000/ICRS if requested, through the full attitude
    # matrix so that roll is converted consistently with RA/Dec.
    if observation_jyear is not None:
        return extract_plate_solve(P.T @ M_corrected)
    return extract_plate_solve(M_corrected)





def _boresight_vec(ra_deg, dec_deg):
    """Unit vector in equatorial frame pointing at (RA, Dec)."""
    r, d = np.radians(ra_deg), np.radians(dec_deg)
    return np.array([np.cos(d)*np.cos(r), np.cos(d)*np.sin(r), np.sin(d)])

def _wrap180(angle):
    """Wrap angle in degrees to (−180, +180]."""
    return (angle + 180.0) % 360.0 - 180.0

def _axis_from_dec_ra(dec_ax_rad, ra_ax_rad):
    cd = np.cos(dec_ax_rad)
    return np.array([cd*np.cos(ra_ax_rad), cd*np.sin(ra_ax_rad), np.sin(dec_ax_rad)])

def _axis_from_nx_ny(nx, ny):
    """Recover unit vector from its x,y components (nz = sqrt(1-nx²-ny²))."""
    nz2 = 1.0 - nx**2 - ny**2
    return np.array([nx, ny, np.sqrt(max(0.0, nz2))])

def _predict_three_solves(n, theta1, theta2, ra0, dec0, roll0):
    """
    Forward model: predict plate-solve outputs for three positions.

    theta1 and theta2 are the platform sweep angles in degrees.
    The physical rotation is M_i = R(+theta * n) @ M_0, i.e. positive theta
    rotates the mount in the direction of n by the right-hand rule.
    This matches the convention used in _signed_sweep_angle.
    """
    M0 = attitude_mat(ra0, dec0, roll0)
    R1 = R.from_rotvec(np.radians(theta1) * n).as_matrix()
    R2 = R.from_rotvec(np.radians(theta2) * n).as_matrix()
    return (extract_plate_solve(M0),
            extract_plate_solve(R1 @ M0),
            extract_plate_solve(R2 @ R1 @ M0))

def _three_solve_cost(params, obs, sigma_ra, sigma_dec, sigma_roll):
    """
    Weighted sum of squared residuals across all three solves.

    Parametrisation: (nx, ny, theta1, theta2, ra0, dec0, roll0)
    where the axis unit vector n = (nx, ny, sqrt(1-nx²-ny²)).
    theta1 and theta2 are the platform sweep angles in degrees, with the
    same sign convention as _predict_three_solves: positive theta rotates
    the mount in the direction of n by the right-hand rule.

    The RA residual is multiplied by cos(Dec) of the measured point so that
    the penalty is in sky-projected degrees rather than RA degrees, making
    the cost isotropic near the pole and preventing the over-weighting of RA
    that caused hundreds of wasted iterations when pointing near Dec=90°.
    For a 10° field (R=5°=0.0873 rad), sigma_roll = 1/R ≈ 11.46 × sigma_ra.
    """
    nx, ny, t1, t2, ra0, dec0, roll0 = params
    nz2 = 1.0 - nx**2 - ny**2
    if nz2 < 0:
        return 1e30
    n = np.array([nx, ny, np.sqrt(nz2)])
    try:
        ps1, ps2, ps3 = _predict_three_solves(n, t1, t2, ra0, dec0, roll0)
    except Exception:
        return 1e30
    total = 0.0
    for pred, meas in zip((ps1, ps2, ps3), obs):
        cos_dec = np.cos(np.radians(meas[1]))
        dra   = _wrap180(pred[0] - meas[0]) * cos_dec   # sky-projected RA
        ddec  = pred[1] - meas[1]
        droll = _wrap180(pred[2] - meas[2])
        total += (dra   / sigma_ra)   ** 2
        total += (ddec  / sigma_dec)  ** 2
        total += (droll / sigma_roll) ** 2
    return total

def _signed_sweep_angle(n_vec, b_from, b_to):
    """
    Signed rotation angle (degrees) from boresight b_from to b_to around n_vec,
    in the sense that R(+theta * n_vec) maps b_from toward b_to.
    """
    pf = b_from - np.dot(n_vec, b_from) * n_vec
    pt = b_to   - np.dot(n_vec, b_to)   * n_vec
    nf, nt = np.linalg.norm(pf), np.linalg.norm(pt)
    if nf < 1e-9 or nt < 1e-9:
        return 0.0
    pf /= nf; pt /= nt
    cos_a = np.clip(np.dot(pf, pt), -1.0, 1.0)
    return (np.sign(np.dot(np.cross(pf, pt), n_vec))
            * np.degrees(np.arccos(cos_a)))


def _three_solve_initial_params(obs, axis_seed):
    """
    Build three candidate starting points for the three-solve optimiser.

    obs       : list of (ra, dec, roll) triples in observation order.
    axis_seed : unit vector of the axis estimate from the two-solve path.

    Returns (x0_pos, x0_neg, x0_xp), each a 7-element list
    (nx, ny, t1, t2, ra0, dec0, roll0) ready to pass to _three_solve_cost.

    nx, ny are the x and y Cartesian components of the axis unit vector,
    with nz = sqrt(1 - nx² - ny²) implicit.  This parametrisation avoids
    the singularity of (RA, Dec) coordinates at the pole.

    t1 and t2 are the signed sweep angles (degrees) from solve 1→2 and
    solve 2→3, computed geometrically from the boresight positions and the
    candidate axis using _signed_sweep_angle.  This is exact for any solve
    ordering and does not assume equal spacing.

    x0_pos : two-solve axis with geometric sweeps (the expected-sign solution).
    x0_neg : same axis with negated sweeps (covers sign ambiguity near the
             axis in the southern hemisphere, where the platform rotation
             direction can appear reversed).
    x0_xp  : RA/Dec cross-product axis (pole of the small circle through the
             three boresights) with its own geometric sweeps.  Tends to be a
             better seed than the two-solve axis when the boresight arc is
             large (far from the mechanical axis).

    The caller evaluates _three_solve_cost at all three and runs L-BFGS-B
    from whichever has the lowest initial cost.
    """
    ra0, dec0, roll0 = obs[0][0], obs[0][1], obs[0][2]

    b1 = _boresight_vec(obs[0][0], obs[0][1])
    b2 = _boresight_vec(obs[1][0], obs[1][1])
    b3 = _boresight_vec(obs[2][0], obs[2][1])

    # ── Two-solve axis seeds ──────────────────────────────────────────────────
    ax = axis_seed
    t1_geo = _signed_sweep_angle(ax, b1, b2)
    t2_geo = _signed_sweep_angle(ax, b2, b3)
    x0_pos = [float(ax[0]), float(ax[1]),  t1_geo,  t2_geo, ra0, dec0, roll0]
    x0_neg = [float(ax[0]), float(ax[1]), -t1_geo, -t2_geo, ra0, dec0, roll0]

    # ── Cross-product axis seed ───────────────────────────────────────────────
    n_xp = np.cross(b1 - b2, b2 - b3)
    nm   = np.linalg.norm(n_xp)
    if nm > 1e-9:
        n_xp /= nm
        # Orient n_xp to match the rotation direction of axis_seed
        if np.dot(n_xp, ax) < 0:
            n_xp = -n_xp
        t1_xp = _signed_sweep_angle(n_xp, b1, b2)
        t2_xp = _signed_sweep_angle(n_xp, b2, b3)
        x0_xp = [float(n_xp[0]), float(n_xp[1]),  t1_xp,  t2_xp, ra0, dec0, roll0]
    else:
        x0_xp = x0_pos   # degenerate: fall back to two-solve seed

    return x0_pos, x0_neg, x0_xp

def _refine_axis_three_solves(obs, axis_seed,
                               sigma_ra, sigma_dec, sigma_roll):
    """
    Refine the axis estimate using all observations and the full cost function.

    Generates three candidate seeds (see _three_solve_initial_params) and
    starts L-BFGS-B from the one with the lowest initial cost.  This ensures
    good convergence whether the scope is near or far from the axis:
    - Near the axis: the two-solve seed (±half sweep) is accurate.
    - Far from the axis: the cross-product seed (arc/sin theta) is accurate.

    Returns (axis, final_cost) where final_cost is the cost function value at
    the solution, ready to use as fit_quality = sqrt(final_cost / n_obs).
    """
    x0_pos, x0_neg, x0_xp = _three_solve_initial_params(obs, axis_seed)
    seeds = [x0_pos, x0_neg, x0_xp]
    costs = [_three_solve_cost(x, obs, sigma_ra, sigma_dec, sigma_roll) for x in seeds]
    best_seed_idx = int(np.argmin(costs))
    x0 = seeds[best_seed_idx]

    result = minimize(_three_solve_cost, x0,
                      args=(obs, sigma_ra, sigma_dec, sigma_roll),
                      method='L-BFGS-B',
                      options={'ftol': 1e-6, 'gtol': 1e-8, 'maxiter': 200})

    # Return best of optimiser and best seed
    if result.fun <= costs[best_seed_idx]:
        final_cost = result.fun
        n = _axis_from_nx_ny(result.x[0], result.x[1])
    else:
        final_cost = costs[best_seed_idx]
        n = _axis_from_nx_ny(x0[0], x0[1])
    if n[2] < 0:
        n = -n
    return n, final_cost



# ── Main function ─────────────────────────────────────────────────────────────

def get_platform_adjustments(solves, latitude, lst_deg,
                              sigma_ra=1/60, sigma_dec=1/60, sigma_roll=11.4592/60,
                              ignore_roll=False,
                              observation_jyear=None):
    """
    Calculate polar-axis misalignment from two or more plate solves.

    Parameters
    ----------
    solves            : iterable of (ra, dec, roll, timestamp) tuples
                        Each tuple is one plate solve:
                          ra        — Right Ascension in degrees
                          dec       — Declination in degrees
                          roll      — Camera roll in degrees
                          timestamp — Time of the solve in seconds (any epoch;
                                      only differences matter).
                        Solves are sorted by timestamp internally (ties keep
                        their input order).  At least two are required; three
                        or more trigger the weighted
                        optimisation.  The latest timestamp is the reference
                        epoch: all earlier RAs are advanced by their individual
                        sidereal drift to match it.  Dec and roll are unaffected.
    latitude          : float   Observer's geographic latitude in degrees.
    lst_deg           : float   Local Sidereal Time at the time of the *last*
                                solve, in degrees (0–360).
                                To convert from hours: lst_deg = lst_hours * 15.
    sigma_ra          : float   Expected 1-sigma RA noise in degrees (default 1').
                                Used only when three or more solves are given.
    sigma_dec         : float   Expected 1-sigma Dec noise in degrees (default 1').
                                Used only when three or more solves are given.
    sigma_roll        : float   Expected 1-sigma roll noise in degrees
                                (default 1/R where R = field radius in radians;
                                for a 10° field, R = 5° = 0.0873 rad giving
                                sigma_roll = 11.4592 x sigma_RA/Dec ≈ 11.46x).
                                Set higher to downweight roll relative to RA/Dec.
                                Used only when three or more solves are given.
    ignore_roll       : bool    If True and three or more solves are given, use
                                the RA/Dec-only cross-product method instead of
                                the weighted optimiser.  Roll values in the
                                input tuples are ignored entirely.  Useful when
                                the camera may have physically rotated between
                                solves (e.g. a hardware flop when changing sides
                                on the scope), which would introduce a systematic
                                roll error that corrupts the optimiser.
                                If the boresights are essentially identical
                                (scope pointing at the mechanical axis),
                                RA/Dec carry no rotation information and all
                                axis quantities are returned as nan.
                                Default False.
    observation_jyear : float or None
                                Julian year of the observation (i.e. today's date),
                                e.g. 2025.4.  When provided, plate-solve coordinates
                                are treated as J2000/ICRS and precessed+nutated to
                                TETE (true equator/equinox of date) via skyfield;
                                roll is corrected automatically via the full 3x3 matrix.
                                If None (default), coordinates are used as-is (JNOW).
                                WARNING: most plate solvers output J2000 — omitting
                                this with J2000 input gives results wrong by ~500".

    Returns
    -------
    dAlt      : float  Altitude error (degrees): how far the axis is above/below pole.
                       +  ->  axis too high  (lower front of wedge to correct).
                       -  ->  axis too low   (raise front of wedge to correct).
    dAz       : float  Azimuth error (degrees): how far the axis is East/West of pole.
                       +  ->  pole-end too far East (move pole-end West to correct).
                       -  ->  pole-end too far West (move pole-end East to correct).
                       In both hemispheres dAlt/dAz describe the pole-pointing end
                       of the axis (N-end in NH, S-end in SH) vs the celestial pole.
                       Azimuth is measured from the pole direction, positive East.
    sweep_deg : float  Signed mechanical rotation swept between first and last solve.
                       + = platform rotated following the stars.
                       - = platform rotated against the stars.
                       If |sweep_deg| < MIN_SWEEP_DEG the solves are too close
                       together; dAlt, dAz, axis_ra, axis_dec are all nan.
    axis_ra   : float  Right Ascension of the computed polar axis (degrees, JNOW).
    axis_dec  : float  Declination of the computed polar axis (degrees, JNOW).
                       A perfect polar axis has Dec = +90 degrees.
    fit_quality : float  RMS residual of the three-solve fit in units of sigma.
                       Computed as sqrt(cost / n_obs) where cost is the value of
                       the weighted cost function (RA, Dec, and roll) evaluated
                       at the recovered axis.  Returns nan for two-solve since
                       there is always an exact solution with zero residual.

                       For the default optimised three-solve: a value near 1.0
                       means each observation is off by about one sigma on
                       average — expected from noise alone.  Values above ~3
                       are worth investigating; above ~10 indicates something
                       is genuinely wrong (failed solve, bumped platform, large
                       camera flop).

                       For ignore_roll=True: the axis is derived from RA/Dec
                       only (cross-product), so the RA/Dec residuals are zero
                       by construction.  fit_quality is computed from the roll
                       residuals alone, using sweep angles derived geometrically
                       from the boresight positions — no free parameters.  This
                       measures how consistent the roll observations are with
                       the RA/Dec-derived axis.  Expected ~1–2 under pure noise
                       (1 effective degree of freedom); significantly higher
                       values indicate a systematic roll error such as a camera
                       flop between solves.
    """
    solves = sorted(solves, key=lambda s: s[3])
    if len(solves) < 2:
        raise ValueError("At least two plate solves are required.")

    SIDEREAL_DEG_PER_SEC = 360.0 / 86164.09

    # 1. Precess all solves from J2000/ICRS to JNOW (TETE) if requested.
    #    Must happen before the sidereal drift correction so that we add RA
    #    in the already-precessed (JNOW) coordinate system.
    if observation_jyear is not None:
        P = _precession_matrix(observation_jyear)
        solves = [
            extract_plate_solve(P @ attitude_mat(ra, dec, roll)) + (t,)
            for ra, dec, roll, t in solves
        ]

    # 2. Advance each solve's RA to the epoch of the *last* solve by adding
    #    its individual sidereal drift.  Dec and roll are unaffected.
    t_ref = solves[-1][3]
    solves = [
        (ra + (t_ref - t) * SIDEREAL_DEG_PER_SEC, dec, roll, t)
        for ra, dec, roll, t in solves
    ]

    # 3. Two-solve axis estimate from the first and last solve.
    #    Used as-is for two solves, and as the seed for the optimiser when
    #    three or more solves are provided.
    ra1, dec1, roll1, _ = solves[0]
    ra2, dec2, roll2, _ = solves[-1]

    m1 = attitude_mat(ra1, dec1, roll1)
    m2 = attitude_mat(ra2, dec2, roll2)
    r_clean = R.from_matrix(m2 @ m1.T).as_matrix()

    cos_theta = np.clip((np.trace(r_clean) - 1.0) / 2.0, -1.0, 1.0)
    sweep_deg = np.degrees(np.arccos(cos_theta))

    nan  = float('nan')
    axis = np.array([
        r_clean[2, 1] - r_clean[1, 2],
        r_clean[0, 2] - r_clean[2, 0],
        r_clean[1, 0] - r_clean[0, 1]
    ])
    norm = np.linalg.norm(axis)
    if norm < 1e-8:
        if cos_theta > 0:
            # No measurable rotation between the solves.
            return nan, nan, 0.0, nan, nan, nan
        # Sweep is numerically 180°: the antisymmetric part of the rotation
        # vanishes, but the axis survives in the symmetric part,
        # R + I = 2·n·nᵀ.  Take its largest column for numerical stability.
        sym  = r_clean + np.eye(3)
        axis = sym[:, np.argmax(np.linalg.norm(sym, axis=0))]
        norm = np.linalg.norm(axis)

    if sweep_deg < MIN_SWEEP_DEG:
        return nan, nan, sweep_deg, nan, nan, nan
    axis /= norm
    if axis[2] < 0:
        axis      = -axis
        sweep_deg = -sweep_deg

    axis_dec = np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0)))
    axis_ra  = np.degrees(np.arctan2(axis[1], axis[0])) % 360.0

    # 4. If three or more solves are given, refine the axis.
    _three_solve_final_cost = float('nan')
    _ignore_roll_final_cost = float('nan')
    if len(solves) >= 3:
        if ignore_roll:
            # RA/Dec-only: find the axis as the pole of the arc defined by
            # the three boresight directions.  Roll is not used at all,
            # making this immune to systematic roll errors (e.g. camera flop).
            # Uses the first, middle, and last solve for the best arc coverage.
            mid = len(solves) // 2
            b1 = _boresight_vec(solves[0][0],   solves[0][1])
            b2 = _boresight_vec(solves[mid][0],  solves[mid][1])
            b3 = _boresight_vec(solves[-1][0],   solves[-1][1])
            n  = np.cross(b1 - b2, b2 - b3)
            nm = np.linalg.norm(n)
            if nm <= 1e-9:
                # Boresights are (nearly) identical — the scope is pointing at
                # the mechanical axis and RA/Dec carry no rotation information.
                # The roll-based two-solve estimate is exactly what the caller
                # asked to avoid, so the axis is undetermined.
                return nan, nan, -sweep_deg, nan, nan, nan
            axis = n / nm
            if axis[2] < 0:
                axis = -axis
            # fit_quality for ignore_roll=True: roll-consistency check.
            # The axis and sweeps are fully determined by the three RA/Dec
            # positions (no free parameters), so the roll residuals measure
            # only how consistent the roll observations are with the
            # RA/Dec-derived axis.  Expected ~1 under pure noise.
            _obs_ir = [(ra, dec, roll) for ra, dec, roll, _ in solves]
            _bs = [_boresight_vec(o[0], o[1]) for o in _obs_ir]

            # Orient axis so sweeps have same sign as the two-solve sweep
            _t1_pos = _signed_sweep_angle( axis, _bs[0], _bs[1])
            _t1_neg = _signed_sweep_angle(-axis, _bs[0], _bs[1])
            _n_ir = axis if abs(_t1_pos - sweep_deg) < abs(_t1_neg - sweep_deg) else -axis
            _t1 = _signed_sweep_angle(_n_ir, _bs[0], _bs[1])
            _t2 = _signed_sweep_angle(_n_ir, _bs[1], _bs[2])

            try:
                _ps = _predict_three_solves(
                    _n_ir, _t1, _t2,
                    _obs_ir[0][0], _obs_ir[0][1], _obs_ir[0][2])
                _ignore_roll_final_cost = sum(
                    (_wrap180(_p[2] - _m[2]) / sigma_roll) ** 2
                    for _p, _m in zip(_ps, _obs_ir))
            except Exception:
                pass
        else:
            obs = [(ra, dec, roll) for ra, dec, roll, _ in solves]
            axis, _three_solve_final_cost = _refine_axis_three_solves(
                obs, axis, sigma_ra, sigma_dec, sigma_roll)
        axis_dec = np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0)))
        axis_ra  = np.degrees(np.arctan2(axis[1], axis[0])) % 360.0

    # 5. Convert the equatorial axis direction to physical mount errors,
    #    using LST to resolve the RA -> azimuth mapping.
    dAlt, dAz = axis_to_altaz_error(axis, latitude, lst_deg)

    # 6. Fit quality: sqrt(final_cost / n_obs) at the optimiser solution.
    #    Uses the cost at the actual solution parameters — no sweep re-estimation.
    #    For ignore_roll=True: roll-only cost at the best-fit sweep for the
    #    cross-product axis — measures roll consistency with the RA/Dec-derived
    #    axis, with expected value ~1 under pure noise.
    fit_quality = float('nan')
    if len(solves) >= 3:
        if ignore_roll and np.isfinite(_ignore_roll_final_cost):
            fit_quality = np.sqrt(_ignore_roll_final_cost / len(solves))
        elif not ignore_roll:
            fit_quality = np.sqrt(_three_solve_final_cost / len(solves))

    return dAlt, dAz, -sweep_deg, axis_ra, axis_dec, fit_quality


# ── Synthetic plate-solve generator ──────────────────────────────────────────

def make_solve_2(ra1, dec1, roll1, latitude, dAlt, dAz, sweep_deg, lst_deg):
    """
    Generate the second plate solve for a known misalignment, sweep and LST.

    Useful for verifying that get_platform_adjustments() recovers the
    inputs exactly, and for building test data sets.
    """
    lat = np.radians(latitude)
    if latitude >= 0:
        # NH: N-end of axis at alt=latitude+dAlt, due North + dAz
        alt = np.radians(latitude + dAlt)
        az  = np.radians(dAz)
    else:
        # SH: S-end of axis at alt=|latitude|+dAlt, due South + dAz
        alt = np.radians(abs(latitude) + dAlt)
        az  = np.radians(180.0 + dAz)

    # Horizontal → equatorial: altitude/azimuth of the axis → (Dec, HA) → RA
    dec_axis = np.arcsin(np.sin(lat)*np.sin(alt) + np.cos(lat)*np.cos(alt)*np.cos(az))
    ha_axis  = np.arctan2(-np.cos(alt)*np.sin(az),
                           np.cos(lat)*np.sin(alt) - np.sin(lat)*np.cos(alt)*np.cos(az))
    ra_axis  = np.radians(lst_deg) - ha_axis      # RA = LST − HA

    cd   = np.cos(dec_axis)
    axis = np.array([cd*np.cos(ra_axis), cd*np.sin(ra_axis), np.sin(dec_axis)])

    M1     = attitude_mat(ra1, dec1, roll1)
    # In the SH the axis points toward SCP (axis[2]<0). Following the stars
    # means rotating around the SCP axis positively, which is a negative
    # rotation around NCP. The sign of from_rotvec therefore stays consistent
    # with NH when we leave the sign as-is after the SH axis construction.
    sign = 1 if latitude < 0 else -1
    Rtrack = R.from_rotvec(np.radians(sign * sweep_deg) * axis).as_matrix()
    M2     = Rtrack @ M1

    return extract_plate_solve(M2)


# ── Demo ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    import time as _time

    observing_latitude = 51.2
    lst                = 112.0    # degrees  (= 7h 28m sidereal time)

    dAlt_true = 1.5               # axis too high by 1.5°
    dAz_true  = 3.0               # axis too far East by 3.0°

    sigma_ra   = sigma_dec = 0.5 / 60            # 0.5 arcmin  (PiFinder/Tetra3 RA/Dec noise)
    sigma_roll = sigma_ra / np.radians(5.0)      # ≈11.46× sigma_ra  (1/R, R = 5° field radius)

    def _make_three_solves(ra1, dec1, roll1, sweep_total):
        """
        Return three plate solves for the given starting position and total sweep.
        Solve 1 is at 0°, solve 3 is at sweep_total°, and solve 2 is placed in
        the middle (sweep_total/2°) so the three solves span the full arc and the
        optimiser has the maximum geometric leverage.
        """
        ra2, dec2, roll2 = make_solve_2(
            ra1=ra1, dec1=dec1, roll1=roll1,
            latitude=observing_latitude,
            dAlt=dAlt_true, dAz=dAz_true,
            sweep_deg=sweep_total / 2,
            lst_deg=lst)
        ra3, dec3, roll3 = make_solve_2(
            ra1=ra1, dec1=dec1, roll1=roll1,
            latitude=observing_latitude,
            dAlt=dAlt_true, dAz=dAz_true,
            sweep_deg=sweep_total,
            lst_deg=lst)
        return ((ra1, dec1, roll1),
                (ra2, dec2, roll2),
                (ra3, dec3, roll3))

    def _mc_test(ra1, dec1, sweep_total, N=300):
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
                return (s[0] + rng.normal(0, sigma_ra),
                        s[1] + rng.normal(0, sigma_dec),
                        s[2] + rng.normal(0, sigma_roll),
                        0)
            sn1, sn2, sn3 = noisy(s1e), noisy(s2e), noisy(s3e)

            def to_n(ar, ad):
                cd = np.cos(np.radians(ad))
                return np.array([cd*np.cos(np.radians(ar)),
                                  cd*np.sin(np.radians(ar)),
                                  np.sin(np.radians(ad))])
            def aerr(n):
                return np.degrees(np.arccos(np.clip(np.dot(n, pax), -1, 1))) * 60

            # Two-solve
            _, _, _, ar, ad, _ = get_platform_adjustments(
                [sn1, sn2], observing_latitude, lst)
            if not np.isnan(ar):
                e2.append(aerr(to_n(ar, ad)))

            # Three-solve optimised — timed individually
            _t = _time.time()
            _, _, _, ar, ad, fq = get_platform_adjustments(
                [sn1, sn2, sn3], observing_latitude, lst,
                sigma_ra=sigma_ra, sigma_dec=sigma_dec, sigma_roll=sigma_roll)
            t3s.append(_time.time() - _t)
            if not np.isnan(ar):
                e3.append(aerr(to_n(ar, ad)))
            if not np.isnan(fq):
                fqs.append(fq)

            # RA/Dec-only via ignore_roll=True
            _, _, _, ar, ad, fq_ir = get_platform_adjustments(
                [sn1, sn2, sn3], observing_latitude, lst,
                sigma_ra=sigma_ra, sigma_dec=sigma_dec, sigma_roll=sigma_roll,
                ignore_roll=True)
            if not np.isnan(ar):
                erd.append(aerr(to_n(ar, ad)))
            if not np.isnan(fq_ir):
                fqs_ir.append(fq_ir)

        a2, a3, ard = np.array(e2), np.array(e3), np.array(erd)
        afq    = np.array(fqs)    if fqs    else np.array([float('nan')])
        afq_ir = np.array(fqs_ir) if fqs_ir else np.array([float('nan')])
        return (np.mean(a2),       np.percentile(a2,    95),
                np.mean(a3),       np.percentile(a3,    95),
                np.mean(ard),      np.percentile(ard,   95),
                np.mean(afq),      np.percentile(afq,   95),
                np.mean(afq_ir),   np.percentile(afq_ir,95),
                np.mean(t3s))

    # ── Build the true platform axis (needed to compute axis errors) ──────────
    lat_r   = np.radians(observing_latitude)
    alt_ax  = np.radians(observing_latitude + dAlt_true)
    az_ax   = np.radians(dAz_true)
    dec_pax = np.arcsin(np.sin(lat_r)*np.sin(alt_ax)
                        + np.cos(lat_r)*np.cos(alt_ax)*np.cos(az_ax))
    ha_pax  = np.arctan2(-np.cos(alt_ax)*np.sin(az_ax),
                          np.cos(lat_r)*np.sin(alt_ax)
                          - np.sin(lat_r)*np.cos(alt_ax)*np.cos(az_ax))
    ra_pax  = np.radians(lst) - ha_pax
    cd      = np.cos(dec_pax)
    pax     = np.array([cd*np.cos(ra_pax), cd*np.sin(ra_pax), np.sin(dec_pax)])

    # ── Monte Carlo comparison across four scenarios ──────────────────────────
    N_MC = 300
    import platform as _platform
    print(f"Monte Carlo N={N_MC}  sigma_RA/Dec={sigma_ra*60:.1f}'  "
          f"sigma_roll={sigma_roll*60:.1f}'  ({sigma_roll/sigma_ra:.0f}x)")
    print(f"Platform: {_platform.node()}  {_platform.processor() or _platform.machine()}  "
          f"Python {_platform.python_version()}")
    print()
    hdr = (f"  {'Pointing':<18} {'Sweep':>7} | "
           f"{'2-solve':>8} {'p95':>7} | "
           f"{'3-solve opt':>11} {'p95':>7} | "
           f"{'RA/Dec only':>11} {'p95':>7} | "
           f"{'fq(3s)':>7} {'p95':>6} | "
           f"{'fq(ir)':>7} {'p95':>6} | {'3s t/call':>9}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for label, (ra1, dec1) in [("Dec=30° (far)",  (180.0, 30.0)),
                                ("Dec=45°",        (180.0, 45.0)),
                                ("Dec=70°",        (180.0, 70.0)),
                                ("Polaris (near)", (37.95, 89.26))]:
        for sweep in [14.0, 37.5, 90.0]:
            m2, p2, m3, p3, mrd, prd, mfq, pfq, mfq_ir, pfq_ir, dt = \
                _mc_test(ra1, dec1, sweep, N=N_MC)
            print(f"  {label:<18} {sweep:>6.0f}° | "
                  f"{m2:>7.2f}' {p2:>6.2f}' | "
                  f"{m3:>10.2f}' {p3:>6.2f}' | "
                  f"{mrd:>10.2f}' {prd:>6.2f}' | "
                  f"{mfq:>6.2f}  {pfq:>5.2f} | "
                  f"{mfq_ir:>6.2f}  {pfq_ir:>5.2f} | {dt:>8.3f}s")
        print()

        # ── Sanity checks ─────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SANITY CHECKS")
    print("="*60)

    sidereal = 360.0 / 86164.09
    gap      = 3600.0   # 1 hour in seconds
    ra0, dec0, roll0 = 180.0, 30.0, 0.0

    # 1. Identical solves, 1 hour apart: platform tracked the stars perfectly.
    #    The time correction cancels the sidereal drift, leaving a rotation equal
    #    to the full sidereal hour — i.e. the platform followed the stars.
    dA, dZ, sw, ar, ad, _ = get_platform_adjustments(
        [(ra0, dec0, roll0, 0.0),
         (ra0, dec0, roll0, gap)],
        observing_latitude, 0.0
    )
    expected_sw = gap * sidereal
    print(f"\nCheck 1 — identical solves, {gap:.0f}s apart (perfect tracking):")
    print(f"  sweep = {sw:+.6f}°  (expected +{expected_sw:.6f}°)  "
          f"{'PASS' if abs(sw - expected_sw) < 1e-6 else 'FAIL'}")

    # 2. Stationary platform, object drifted by 1 sidereal hour in RA.
    #    After the time correction both attitude matrices are identical →
    #    no rotation information, sweep = 0 and axis is undefined.
    ra2_drifted = ra0 + gap * sidereal
    dA, dZ, sw, ar, ad, _ = get_platform_adjustments(
        [(ra0, dec0, roll0, 0.0),
         (ra2_drifted, dec0, roll0, gap)],
        observing_latitude, 0.0
    )
    print(f"\nCheck 2 — stationary platform, object drifted 1 sidereal hour:")
    print(f"  sweep = {sw:+.6f}°  (expected 0°)  "
          f"{'PASS' if abs(sw) < 1e-6 else 'FAIL'}")
    print(f"  axis RA/Dec = ({ar:.4f}°, {ad:.4f}°)  "
          f"(undefined — no platform rotation to analyse)")

    # 3. Boresight pointing directly at the rotation axis: only roll changes.
    #    When the camera points at the platform's own axis, rotation around that
    #    axis leaves RA and Dec unchanged and maps entirely onto the roll.
    #    The recovered sweep should equal the roll difference exactly.
    sweep3 = 14.0

    # Reconstruct the axis direction from the known errors used in the demo
    alt3   = np.radians(observing_latitude + dAlt_true)
    az3    = np.radians(dAz_true)
    lat3   = np.radians(observing_latitude)
    dec_ax = np.arcsin(np.sin(lat3)*np.sin(alt3) + np.cos(lat3)*np.cos(alt3)*np.cos(az3))
    ha_ax  = np.arctan2(-np.cos(alt3)*np.sin(az3),
                         np.cos(lat3)*np.sin(alt3) - np.sin(lat3)*np.cos(alt3)*np.cos(az3))
    ra_ax  = np.radians(lst) - ha_ax
    cd3    = np.cos(dec_ax)
    axis3  = np.array([cd3*np.cos(ra_ax), cd3*np.sin(ra_ax), np.sin(dec_ax)])

    ra_pt  = np.degrees(ra_ax) % 360
    dec_pt = np.degrees(dec_ax)

    # Construct solve_2 by rotating around the axis
    M1_3   = attitude_mat(ra_pt, dec_pt, 0.0)
    Rt3    = R.from_rotvec(np.radians(-sweep3) * axis3).as_matrix()
    ra2_3, dec2_3, roll2_3 = extract_plate_solve(Rt3 @ M1_3)

    dA3, dZ3, sw3, ar3, ad3, _ = get_platform_adjustments(
        [(ra_pt, dec_pt, 0.0, 0),
         (ra2_3, dec2_3, roll2_3, 0)],
        observing_latitude, lst
    )

    print(f"\nCheck 3 — boresight pointing at the rotation axis (only roll changes):")
    print(f"  solve_1 roll = 0.0000°,  solve_2 roll = {roll2_3:.6f}°")
    print(f"  RA change = {ra2_3 - ra_pt:.2e}°,  Dec change = {dec2_3 - dec_pt:.2e}°")
    print(f"  sweep = {sw3:+.6f}°  (expected +{sweep3:.6f}°)  "
          f"{'PASS' if abs(sw3 - sweep3) < 1e-6 else 'FAIL'}")
    print(f"  dAlt  = {dA3:+.6f}°  (expected +{dAlt_true:.6f}°)  "
          f"{'PASS' if abs(dA3 - dAlt_true) < 1e-6 else 'FAIL'}")
    print(f"  dAz   = {dZ3:+.6f}°  (expected +{dAz_true:.6f}°)  "
          f"{'PASS' if abs(dZ3 - dAz_true) < 1e-6 else 'FAIL'}")
    print(f"  (axis RA/Dec recovered directly from the boresight pointing)")

    # ── Precession test ───────────────────────────────────────────────────────
    # Aldebaran (alpha Tau), well-tabulated bright star.
    # J2000 (ICRS): RA = 68.9802°, Dec = 16.5093°
    # We verify that _precession_matrix() applied to the J2000 cartesian
    # unit vector recovers the expected TETE coordinates.

    print("\n" + "="*60)
    print("PRECESSION TEST (precession + nutation via TETE)")
    print("="*60)

    aldebaran_ra_j2000  = 68.9802    # degrees (ICRS)
    aldebaran_dec_j2000 = 16.5093
    obs_jyear           = 2025.41    # 2025-06-01

    # Ground truth for 2025-06-01, cross-checked once against astropy:
    # FK5 mean-of-date (precession only) is RA=69.3451, Dec=16.5596;
    # TETE adds nutation (~8" at this epoch).
    aldebaran_ra_tete  = 69.3452
    aldebaran_dec_tete = 16.5619

    # Apply precession+nutation matrix and compare
    vec_j2000 = np.array([
        np.cos(np.radians(aldebaran_dec_j2000)) * np.cos(np.radians(aldebaran_ra_j2000)),
        np.cos(np.radians(aldebaran_dec_j2000)) * np.sin(np.radians(aldebaran_ra_j2000)),
        np.sin(np.radians(aldebaran_dec_j2000))
    ])
    P_test   = _precession_matrix(obs_jyear)
    vec_tete = P_test @ vec_j2000
    ra_out   = np.degrees(np.arctan2(vec_tete[1], vec_tete[0])) % 360
    dec_out  = np.degrees(np.arcsin(np.clip(vec_tete[2], -1, 1)))

    err_ra_arcsec  = abs(ra_out  - aldebaran_ra_tete)  * 3600
    err_dec_arcsec = abs(dec_out - aldebaran_dec_tete) * 3600

    print(f"\nAldebaran (alpha Tau), precessed+nutated to {obs_jyear}:")
    print(f"  Input  J2000:       RA={aldebaran_ra_j2000:.4f}°  Dec={aldebaran_dec_j2000:.4f}°")
    print(f"  Output TETE:        RA={ra_out:.4f}°  Dec={dec_out:.4f}°")
    print(f"  Expected TETE:      RA={aldebaran_ra_tete:.4f}°  Dec={aldebaran_dec_tete:.4f}°")
    print(f"  Error:              ΔRA={err_ra_arcsec:.2f}\"  ΔDec={err_dec_arcsec:.2f}\"")

    # Expected values are quantised to 4 decimals (0.36"); 1" tolerance.
    tol_arcsec = 1.0
    ra_pass  = err_ra_arcsec  < tol_arcsec
    dec_pass = err_dec_arcsec < tol_arcsec
    print(f"  RA  within {tol_arcsec}\": {'PASS' if ra_pass  else 'FAIL'}")
    print(f"  Dec within {tol_arcsec}\": {'PASS' if dec_pass else 'FAIL'}")

    # ── J2000 pole precession test ─────────────────────────────────────────────
    # Both solves point at the J2000 pole (RA=0, Dec=90) with only the roll
    # changing between them — meaning the platform axis IS the J2000 pole.
    # After precessing to JNOW the function sees that axis offset from the true
    # pole by the precession amount, and should recover the correct dAlt/dAz.
    # The J2000 pole traces a ~23.4° radius circle around the ecliptic pole at
    # ~50.3"/yr in ecliptic longitude; its straight angular distance from the
    # JNOW pole grows at only ~20"/yr (chord vs arc on that circle).
    # The expected axis comes from _precession_matrix directly, so this checks
    # the solve -> axis -> alt/az pipeline, not the matrix itself.

    print("\n" + "="*60)
    print("J2000 POLE PRECESSION TEST")
    print("="*60)

    lat_p   = 51.2
    lst_p   = 0.0
    jyear_p = float(_SKYFIELD_TS.now().J)   # always use today
    sweep_p = 14.0

    dAlt_p, dAz_p, sw_p, ar_p, ad_p, _ = get_platform_adjustments(
        [(0.0, 90.0, 0.0,     0),
         (0.0, 90.0, sweep_p, 0)],
        lat_p, lst_p,
        observation_jyear=jyear_p
    )

    # Expected axis: the J2000 pole expressed in JNOW, straight from the
    # precession matrix — no hardcoded rounded constants.
    # Small residuals (~8") in axis RA arise because extract_plate_solve
    # loses precision in roll near Dec=90° (gimbal zone), which feeds back
    # into attitude_mat.  This only affects the degenerate pointing-at-pole
    # case; normal use away from the pole is unaffected.
    exp_axis_p   = _precession_matrix(jyear_p) @ np.array([0.0, 0.0, 1.0])
    exp_ax_ra_p  = np.degrees(np.arctan2(exp_axis_p[1], exp_axis_p[0])) % 360
    exp_ax_dec_p = np.degrees(np.arcsin(np.clip(exp_axis_p[2], -1, 1)))
    exp_dAlt_p, exp_dAz_p = axis_to_altaz_error(exp_axis_p, lat_p, lst_p)
    tol_dAlt_p = 1.0 / 3600    # 1 arcsecond
    tol_dAz_p  = 1.0 / 3600
    tol_ax_ra_p = 10.0 / 3600  # relaxed for the gimbal-zone roll imprecision

    print(f"\nsolve_1 (J2000): RA=0°  Dec=90°  roll=0°")
    print(f"solve_2 (J2000): RA=0°  Dec=90°  roll={sweep_p}°  (only roll changed)")
    print(f"observation_jyear={jyear_p}")
    print(f"\n  dAlt = {dAlt_p:+.6f}°  (expected {exp_dAlt_p:+.6f}°)  "
          f"err={(dAlt_p-exp_dAlt_p)*3600:.2f}\"  "
          f"{'PASS' if abs(dAlt_p-exp_dAlt_p) < tol_dAlt_p else 'FAIL'}")
    print(f"  dAz  = {dAz_p:+.6f}°  (expected {exp_dAz_p:+.6f}°)  "
          f"err={(dAz_p-exp_dAz_p)*3600:.2f}\"  "
          f"{'PASS' if abs(dAz_p-exp_dAz_p) < tol_dAz_p else 'FAIL'}")
    print(f"  sweep = {sw_p:+.6f}°  (expected +{sweep_p:.6f}°)  "
          f"{'PASS' if abs(sw_p-sweep_p) < 1e-6 else 'FAIL'}")
    print(f"  Recovered axis (JNOW): RA={ar_p:.4f}°  Dec={ad_p:.4f}°")
    print(f"  Expected  axis (JNOW): RA={exp_ax_ra_p:.4f}°  Dec={exp_ax_dec_p:.4f}°  (skyfield TETE)")
    print(f"  Axis RA err={(ar_p-exp_ax_ra_p)*3600:.2f}\"  "
          f"{'PASS' if abs(ar_p-exp_ax_ra_p) < tol_ax_ra_p else 'FAIL'} "
          f"(relaxed tol: roll imprecision near Dec=90°)")
    print(f"  (J2000 pole is {(90-ad_p)*3600:.1f}\" from JNOW pole due to precession)")

    # ── Southern hemisphere sanity check ──────────────────────────────────────
    # At lat=-34° (Sydney), axis S-end 1.5° too high and 3° too far East.
    # dAlt and dAz should recover with the same sign convention as NH.
    print("\n" + "="*60)
    print("SOUTHERN HEMISPHERE CHECK")
    print("="*60)

    lat_sh   = -34.0
    lst_sh   = 0.0
    dAlt_sh  = 1.5
    dAz_sh   = 3.0
    sweep_sh = 14.0

    ra2_sh, dec2_sh, roll2_sh = make_solve_2(
        180.0, -30.0, 0.0, lat_sh, dAlt_sh, dAz_sh, sweep_sh, lst_sh)

    dA_sh, dZ_sh, sw_sh, ar_sh, ad_sh, _ = get_platform_adjustments(
        [(180.0, -30.0, 0.0, 0), (ra2_sh, dec2_sh, roll2_sh, 0)],
        lat_sh, lst_sh)

    print(f"\n  lat={lat_sh}°  truth: dAlt={dAlt_sh:+.4f}°  dAz={dAz_sh:+.4f}°  sweep={sweep_sh:+.4f}°")
    print(f"  recovered:   dAlt={dA_sh:+.4f}°  dAz={dZ_sh:+.4f}°  sweep={sw_sh:+.4f}°")
    print(f"  dAlt: {'PASS' if abs(dA_sh - dAlt_sh) < 1e-4 else 'FAIL'}")
    print(f"  dAz:  {'PASS' if abs(dZ_sh - dAz_sh)  < 1e-4 else 'FAIL'}")
    print(f"  sweep: {'PASS' if abs(sw_sh - sweep_sh) < 1e-4 else 'FAIL'}")

    # ── correction_target sanity checks ───────────────────────────────────────
    print("\n" + "="*60)
    print("CORRECTION_TARGET CHECKS")
    print("="*60)

    # Helper: convert equatorial to horizontal coordinates
    def _to_altaz(ra_deg, dec_deg, lat_deg, lst_deg):
        lat = np.radians(lat_deg); ha = np.radians(lst_deg) - np.radians(ra_deg)
        dec = np.radians(dec_deg)
        sa  = np.sin(lat)*np.sin(dec) + np.cos(lat)*np.cos(dec)*np.cos(ha)
        alt = np.degrees(np.arcsin(np.clip(sa, -1, 1)))
        az  = np.degrees(np.arctan2(
            -np.cos(dec)*np.sin(ha),
             np.cos(lat)*np.sin(dec) - np.sin(lat)*np.cos(dec)*np.cos(ha)))
        return alt, az

    # ── Check A: scope at mechanical axis (NH) ─────────────────────────────────
    # If all three solves point at the same RA/Dec (only roll changes), the scope
    # is at the mechanical axis.  After the Alt/Az correction it should be at the
    # true pole: Alt = latitude, Az = 0° (due North).
    print("\n── Check A: scope at mechanical axis (NH, lat=51.2°) ──")
    lat_a, lst_a, dAlt_a, dAz_a, sw_a = 51.2, 45.0, 1.5, 3.0, 14.0
    lat_r_a = np.radians(lat_a)
    alt_r_a = np.radians(lat_a + dAlt_a); az_r_a = np.radians(dAz_a)
    dec_ax_a = np.arcsin(np.sin(lat_r_a)*np.sin(alt_r_a)
                         + np.cos(lat_r_a)*np.cos(alt_r_a)*np.cos(az_r_a))
    ha_ax_a  = np.arctan2(-np.cos(alt_r_a)*np.sin(az_r_a),
                           np.cos(lat_r_a)*np.sin(alt_r_a)
                           - np.sin(lat_r_a)*np.cos(alt_r_a)*np.cos(az_r_a))
    ra_ax_a  = np.degrees(np.radians(lst_a) - ha_ax_a) % 360
    dec_ax_a = np.degrees(dec_ax_a)

    solves_a = [(ra_ax_a, dec_ax_a, 0.,     0),
                (ra_ax_a, dec_ax_a, sw_a,   0),
                (ra_ax_a, dec_ax_a, 2*sw_a, 0)]
    _, _, _, ax_ra_a, ax_dec_a, _ = get_platform_adjustments(solves_a, lat_a, lst_a)
    ra_ta, dec_ta, _ = correction_target(ax_ra_a, ax_dec_a,
                                          (ra_ax_a, dec_ax_a, 2*sw_a))
    alt_ta, az_ta = _to_altaz(ra_ta, dec_ta, lat_a, lst_a)
    tol = 1e-4
    print(f"  Scope at axis: RA={ra_ax_a:.4f}°  Dec={dec_ax_a:.4f}°")
    print(f"  correction_target: RA={ra_ta:.4f}°  Dec={dec_ta:.4f}°")
    print(f"  Horizontal: Alt={alt_ta:.4f}°  Az={az_ta:.4f}°")
    print(f"  Expected:   Alt={lat_a:.4f}°  Az=0.0000°")
    print(f"  Alt: {'PASS' if abs(alt_ta - lat_a) < tol else 'FAIL'}  "
          f"Az: {'PASS' if abs(az_ta) < tol else 'FAIL'}")

    # ── Check B: scope at mechanical axis (SH) ─────────────────────────────────
    # In SH the pole-pointing end is the S-end (near SCP, above the horizon).
    # With the scope at the S-end and only roll changing between solves,
    # the two-solve path uses roll to recover the axis.  After the Alt/Az
    # correction the target should be at Alt=|lat|, Az=180° (the SCP).
    print("\n── Check B: scope at mechanical axis (SH, lat=-34°) ──")
    lat_b, lst_b, dAlt_b, dAz_b, sw_b = -34.0, 60.0, 1.5, 3.0, 14.0
    lat_r_b = np.radians(lat_b)
    alt_r_b = np.radians(abs(lat_b) + dAlt_b)
    az_r_b  = np.radians(180.0 + dAz_b)
    dec_s_b = np.arcsin(np.sin(lat_r_b)*np.sin(alt_r_b)
                         + np.cos(lat_r_b)*np.cos(alt_r_b)*np.cos(az_r_b))
    ha_s_b  = np.arctan2(-np.cos(alt_r_b)*np.sin(az_r_b),
                          np.cos(lat_r_b)*np.sin(alt_r_b)
                          - np.sin(lat_r_b)*np.cos(alt_r_b)*np.cos(az_r_b))
    ra_s_b  = np.radians(lst_b) - ha_s_b
    cd_b    = np.cos(dec_s_b)
    s_end_b = np.array([cd_b*np.cos(ra_s_b), cd_b*np.sin(ra_s_b), np.sin(dec_s_b)])
    ra_s_deg_b  = np.degrees(np.arctan2(s_end_b[1], s_end_b[0])) % 360
    dec_s_deg_b = np.degrees(np.arcsin(np.clip(s_end_b[2], -1, 1)))
    # Two solves at S-end, only roll changes: two-solve uses roll to find the axis
    _, _, _, ax_ra_b, ax_dec_b, _ = get_platform_adjustments(
        [(ra_s_deg_b, dec_s_deg_b, 0.,    0),
         (ra_s_deg_b, dec_s_deg_b, sw_b,  0)],
        lat_b, lst_b)
    ra_tb, dec_tb, _ = correction_target(ax_ra_b, ax_dec_b,
                                          (ra_s_deg_b, dec_s_deg_b, sw_b))
    alt_tb, az_tb = _to_altaz(ra_tb, dec_tb, lat_b, lst_b)
    az_tb_norm = az_tb if az_tb >= 0 else az_tb + 360
    tol_b = 1e-4
    print(f"  S-end (scope): RA={ra_s_deg_b:.4f}°  Dec={dec_s_deg_b:.4f}°  "
          f"(Alt={abs(lat_b)+dAlt_b:.1f}°, Az=180°+{dAz_b}° from SH observer)")
    print(f"  Recovered axis: RA={ax_ra_b:.4f}°  Dec={ax_dec_b:.4f}°")
    print(f"  correction_target: RA={ra_tb:.4f}°  Dec={dec_tb:.4f}°")
    print(f"  Horizontal: Alt={alt_tb:.4f}°  Az={az_tb:.4f}° (normalised: {az_tb_norm:.4f}°)")
    print(f"  Expected:   Alt={abs(lat_b):.4f}°  Az=180.0000°")
    print(f"  Alt: {'PASS' if abs(alt_tb - abs(lat_b)) < tol_b else 'FAIL'}  "
          f"Az: {'PASS' if abs(az_tb_norm - 180.0) < tol_b else 'FAIL'}")

    # ── Check C: J2000 pole as axis, precession applied ────────────────────────
    # The mechanical axis IS the J2000 pole.  After precessing to JNOW the axis
    # is offset from the true pole by the precession amount.  correction_target
    # should return the JNOW NCP expressed in J2000 coordinates — the same point
    # as back-precessing [0,0,1] from JNOW to J2000.
    print("\n── Check C: J2000 pole as mechanical axis, precession applied ──")
    jyear_c = float(_SKYFIELD_TS.now().J)
    _, _, _, ax_ra_c, ax_dec_c, _ = get_platform_adjustments(
        [(0., 90., 0., 0), (0., 90., 14., 0)],
        51.2, 0., observation_jyear=jyear_c)
    # Pass the J2000 last solve directly — correction_target precesses internally
    ra_tc, dec_tc, _ = correction_target(
        ax_ra_c, ax_dec_c,
        (0., 90., 14.),
        observation_jyear=jyear_c)
    # Ground truth: TETE Dec=90° (JNOW NCP) expressed in ICRS/J2000,
    # i.e. the JNOW pole back-rotated through the precession matrix.
    gt_vec_c = _precession_matrix(jyear_c).T @ np.array([0.0, 0.0, 1.0])
    gt_ra_c  = np.degrees(np.arctan2(gt_vec_c[1], gt_vec_c[0])) % 360
    gt_dec_c = np.degrees(np.arcsin(np.clip(gt_vec_c[2], -1, 1)))
    # Near Dec=90° RA in degrees is not meaningful — compare by angular separation
    t_vec_c = np.array([
        np.cos(np.radians(dec_tc)) * np.cos(np.radians(ra_tc)),
        np.cos(np.radians(dec_tc)) * np.sin(np.radians(ra_tc)),
        np.sin(np.radians(dec_tc)),
    ])
    sep_arcsec = np.degrees(
        np.arccos(np.clip(np.dot(t_vec_c, gt_vec_c), -1, 1))) * 3600
    tol_c = 30.0   # arcseconds — relaxed for gimbal zone near Dec=90
    print(f"  observation_jyear = {jyear_c:.4f}")
    print(f"  Recovered axis (JNOW): RA={ax_ra_c:.4f}\u00b0  Dec={ax_dec_c:.4f}\u00b0")
    print(f"  correction_target (J2000): RA={ra_tc:.4f}\u00b0  Dec={dec_tc:.4f}\u00b0")
    print(f"  Expected (TETE NCP->ICRS): RA={gt_ra_c:.4f}\u00b0  Dec={gt_dec_c:.4f}\u00b0")
    print(f"  Angular separation: {sep_arcsec:.1f}\"")
    print(f"  Within {tol_c:.0f}\": "
          f"{'PASS' if sep_arcsec < tol_c else 'FAIL'}")
    prec_c = (90.0 - ax_dec_c) * 3600
    print(f"  (J2000 pole is {prec_c:.1f}\" from JNOW pole -- precession offset)")
