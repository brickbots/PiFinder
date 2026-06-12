"""
polar_alignment.solver
======================
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
from skyfield.constants import C as _SPEED_OF_LIGHT_M_S
from skyfield.framelib import (
    true_equator_and_equinox_of_date as _SKYFIELD_TETE_FRAME,
)

from PiFinder.calc_utils import sf_utils

# Minimum angular sweep between the first and last solve for a valid result.
# If the recovered sweep is below this threshold, the solves are too close
# together to reliably determine the axis direction, and (nan, nan) is
# returned for the axis quantities.  The sweep itself is still returned so
# the caller can report it to the user and ask for more platform rotation.
MIN_SWEEP_DEG = 3.0


# ── Low-level rotation helpers ────────────────────────────────────────────────


def _Rz(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _Ry(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


# ── Precession ───────────────────────────────────────────────────────────────


def _precession_matrix(jyear):
    """
    Rotation matrix from ICRS/J2000.0 to the true equator and equinox of
    date (TETE) at Julian year `jyear`, incorporating both precession and
    nutation (peak nutation amplitude ~17"), via skyfield (already a
    PiFinder dependency).
    """
    return _SKYFIELD_TETE_FRAME.rotation_at(sf_utils.ts.J(jyear))


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
    dec = np.degrees(np.arcsin(np.clip(M[2, 2], -1.0, 1.0)))
    ra = np.degrees(np.arctan2(M[1, 2], M[0, 2])) % 360.0
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
    ra_ax = np.degrees(np.arctan2(axis[1], axis[0]))
    ha_ax = lst_deg - ra_ax  # HA = LST − RA  (the key step)

    lat = np.radians(latitude_deg)
    dec = np.radians(dec_ax)
    ha = np.radians(ha_ax)

    # Standard equatorial → horizontal transformation
    sin_alt = np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.cos(ha)
    alt = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))

    az = np.degrees(
        np.arctan2(
            -np.cos(dec) * np.sin(ha),
            np.cos(lat) * np.sin(dec) - np.sin(lat) * np.cos(dec) * np.cos(ha),
        )
    )

    if latitude_deg >= 0:
        # NH: pole-pointing end is the N-end; reference is NCP (due North)
        dAlt = alt - latitude_deg
        dAz = az
    else:
        # SH: pole-pointing end is the S-end; reference is SCP (due South)
        dAlt = alt - abs(latitude_deg)
        dAz = az - 180.0
        if dAz > 180:
            dAz -= 360
        if dAz < -180:
            dAz += 360

    return dAlt, dAz


def correction_target(
    axis_ra, axis_dec, last_solve, latitude, lst_deg, observation_jyear=None
):
    """
    Compute the coordinates the user must centre after applying the
    polar-axis correction with the mount's Alt/Az adjusters.

    The correction is modelled as the PHYSICAL adjuster composition:
    first a rotation about the local vertical (azimuth knob), then a
    rotation about the horizontal east-west altitude pin.  Applied in
    that order with the knob amounts equal to the azimuth and altitude
    coordinate differences, this composition places the mechanical axis
    on the celestial pole EXACTLY, at any error magnitude — unlike the
    minimal 3D rotation axis→NCP, which differs from what the knobs can
    realise at second order (≈ error²: ~3' residual from a 2° start,
    ~1.8° residual from a 10° start when the boresight is chased).

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
    latitude   : float  Observer latitude in degrees (south negative).
    lst_deg    : float  Local sidereal time in degrees.  Together with
                        latitude this fixes the local vertical, which the
                        physical adjusters rotate about.
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
    axis = _boresight_vec(axis_ra, axis_dec)

    # Precess last_solve from J2000/ICRS to JNOW so it matches the axis frame.
    ra_ls, dec_ls, roll_ls = last_solve[0], last_solve[1], last_solve[2]
    if observation_jyear is not None:
        P = _precession_matrix(observation_jyear)
        ra_ls, dec_ls, roll_ls = extract_plate_solve(
            P @ attitude_mat(ra_ls, dec_ls, roll_ls)
        )

    # Local vertical in JNOW equatorial components.
    phi = np.radians(latitude)
    lst = np.radians(lst_deg)
    zen = np.array([np.cos(phi) * np.cos(lst), np.cos(phi) * np.sin(lst), np.sin(phi)])

    ncp = np.array([0.0, 0.0, 1.0])  # target axis direction (JNOW pole)
    if observation_jyear is not None:
        # Annual aberration: blend geometric pole (JNOW, no aberration) →
        # apparent pole (where the geometric JNOW pole appears in the sky)
        # by cos(theta), theta = sweep cone angle.  Near-pole sweeps need
        # the apparent pole, great-circle sweeps the geometric one; the
        # blend is exact to first order in v/c.
        t_obs = sf_utils.ts.J(observation_jyear)
        v_e = sf_utils.eph["earth"].at(t_obs).velocity.m_per_s
        cos_theta = np.dot(axis, _boresight_vec(ra_ls, dec_ls))  # SIGNED
        ncp = ncp - cos_theta * (P @ v_e) / _SPEED_OF_LIGHT_M_S
        ncp = ncp / np.linalg.norm(ncp)

    S = _altaz_knob_rotation(axis, ncp, zen)

    # Apply the physical correction to the last-solve attitude (JNOW)
    M_last = attitude_mat(ra_ls, dec_ls, roll_ls)
    M_corrected = S @ M_last

    # Precess back to J2000/ICRS if requested, through the full attitude
    # matrix so that roll is converted consistently with RA/Dec.
    if observation_jyear is not None:
        return extract_plate_solve(P.T @ M_corrected)
    return extract_plate_solve(M_corrected)


def _altaz_knob_rotation(axis, target, zen):
    """
    Rotation realised by the mount's physical adjusters that carries
    ``axis`` onto ``target``: first the azimuth knob (about the local
    vertical ``zen``), then the altitude pin (about the horizontal normal
    of the shared vertical plane).  All vectors are unit vectors in the
    same equatorial frame.
    """
    # ── Step 1: azimuth knob ──────────────────────────────────────────────────
    # Rotate about the local vertical until the axis lies in the same
    # vertical plane as the target.  This changes every azimuth by exactly
    # the knob angle and no altitude — so the knob angle is simply the
    # signed angle between the horizontal projections.
    n_h = axis - np.dot(axis, zen) * zen
    t_h = target - np.dot(target, zen) * zen
    if np.linalg.norm(n_h) > 1e-12 and np.linalg.norm(t_h) > 1e-12:
        d_az = np.arctan2(np.dot(np.cross(n_h, t_h), zen), np.dot(n_h, t_h))
        R_az = R.from_rotvec(d_az * zen).as_matrix()
    else:
        R_az = np.eye(3)  # axis or pole at the zenith: no azimuth dof
    n1 = R_az @ axis

    # ── Step 2: altitude knob ─────────────────────────────────────────────────
    # n1 and the target now share a vertical plane; the altitude pin is the
    # horizontal normal of that plane, so the in-plane minimal rotation from
    # n1 to the target IS the altitude-knob rotation.
    c = np.cross(n1, target)
    s = np.linalg.norm(c)
    cosg = np.clip(np.dot(n1, target), -1.0, 1.0)
    if s < 1e-15:
        if cosg > 0.0:
            R_alt = np.eye(3)
        else:
            # Antipodal within the plane: 180° about the horizontal pin.
            pin = np.cross(zen, target)
            pin /= np.linalg.norm(pin)
            R_alt = R.from_rotvec(np.pi * pin).as_matrix()
    else:
        R_alt = R.from_rotvec(np.arctan2(s, cosg) * (c / s)).as_matrix()

    return R_alt @ R_az


def _boresight_vec(ra_deg, dec_deg):
    """Unit vector in equatorial frame pointing at (RA, Dec)."""
    r, d = np.radians(ra_deg), np.radians(dec_deg)
    return np.array([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)])


def _wrap180(angle):
    """Wrap angle in degrees to (−180, +180]."""
    return (angle + 180.0) % 360.0 - 180.0


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
    return (
        extract_plate_solve(M0),
        extract_plate_solve(R1 @ M0),
        extract_plate_solve(R2 @ R1 @ M0),
    )


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
        dra = _wrap180(pred[0] - meas[0]) * cos_dec  # sky-projected RA
        ddec = pred[1] - meas[1]
        droll = _wrap180(pred[2] - meas[2])
        total += (dra / sigma_ra) ** 2
        total += (ddec / sigma_dec) ** 2
        total += (droll / sigma_roll) ** 2
    return total


def _signed_sweep_angle(n_vec, b_from, b_to):
    """
    Signed rotation angle (degrees) from boresight b_from to b_to around n_vec,
    in the sense that R(+theta * n_vec) maps b_from toward b_to.
    """
    pf = b_from - np.dot(n_vec, b_from) * n_vec
    pt = b_to - np.dot(n_vec, b_to) * n_vec
    nf, nt = np.linalg.norm(pf), np.linalg.norm(pt)
    if nf < 1e-9 or nt < 1e-9:
        return 0.0
    pf /= nf
    pt /= nt
    cos_a = np.clip(np.dot(pf, pt), -1.0, 1.0)
    return np.sign(np.dot(np.cross(pf, pt), n_vec)) * np.degrees(np.arccos(cos_a))


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
    x0_pos = [float(ax[0]), float(ax[1]), t1_geo, t2_geo, ra0, dec0, roll0]
    x0_neg = [float(ax[0]), float(ax[1]), -t1_geo, -t2_geo, ra0, dec0, roll0]

    # ── Cross-product axis seed ───────────────────────────────────────────────
    n_xp = np.cross(b1 - b2, b2 - b3)
    nm = np.linalg.norm(n_xp)
    if nm > 1e-9:
        n_xp /= nm
        # Orient n_xp to match the rotation direction of axis_seed
        if np.dot(n_xp, ax) < 0:
            n_xp = -n_xp
        t1_xp = _signed_sweep_angle(n_xp, b1, b2)
        t2_xp = _signed_sweep_angle(n_xp, b2, b3)
        x0_xp = [float(n_xp[0]), float(n_xp[1]), t1_xp, t2_xp, ra0, dec0, roll0]
    else:
        x0_xp = x0_pos  # degenerate: fall back to two-solve seed

    return x0_pos, x0_neg, x0_xp


def _refine_axis_three_solves(obs, axis_seed, sigma_ra, sigma_dec, sigma_roll):
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

    result = minimize(
        _three_solve_cost,
        x0,
        args=(obs, sigma_ra, sigma_dec, sigma_roll),
        method="L-BFGS-B",
        options={"ftol": 1e-6, "gtol": 1e-8, "maxiter": 200},
    )

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


# ── Pipeline stages ───────────────────────────────────────────────────────────

_SIDEREAL_DEG_PER_SEC = 360.0 / 86164.09


def _epoch_align_solves(solves, observation_jyear):
    """
    Express every solve in the equatorial frame at the epoch of the last solve.

    First precess all solves from J2000/ICRS to JNOW (TETE) if
    observation_jyear is given — this must happen before the sidereal drift
    correction so that RA is advanced in the already-precessed (JNOW)
    coordinate system.  Then advance each solve's RA to the epoch of the
    *last* solve by adding its individual sidereal drift.  Dec and roll are
    unaffected.
    """
    if observation_jyear is not None:
        P = _precession_matrix(observation_jyear)
        solves = [
            extract_plate_solve(P @ attitude_mat(ra, dec, roll)) + (t,)
            for ra, dec, roll, t in solves
        ]

    t_ref = solves[-1][3]
    return [
        (ra + (t_ref - t) * _SIDEREAL_DEG_PER_SEC, dec, roll, t)
        for ra, dec, roll, t in solves
    ]


def _two_solve_axis(solve_a, solve_b):
    """
    Axis and sweep of the relative rotation between two plate solves.

    Returns (axis, sweep_deg):
      axis      : unit vector with axis[2] >= 0, or None when there is no
                  measurable rotation between the solves (sweep_deg is 0.0).
      sweep_deg : sweep angle in degrees; negated when the axis had to be
                  flipped to the axis[2] >= 0 hemisphere.
    """
    ra1, dec1, roll1, _ = solve_a
    ra2, dec2, roll2, _ = solve_b

    m1 = attitude_mat(ra1, dec1, roll1)
    m2 = attitude_mat(ra2, dec2, roll2)
    r_clean = R.from_matrix(m2 @ m1.T).as_matrix()

    cos_theta = np.clip((np.trace(r_clean) - 1.0) / 2.0, -1.0, 1.0)
    sweep_deg = np.degrees(np.arccos(cos_theta))

    axis = np.array(
        [
            r_clean[2, 1] - r_clean[1, 2],
            r_clean[0, 2] - r_clean[2, 0],
            r_clean[1, 0] - r_clean[0, 1],
        ]
    )
    norm = np.linalg.norm(axis)
    if norm < 1e-8:
        if cos_theta > 0:
            return None, 0.0
        # Sweep is numerically 180°: the antisymmetric part of the rotation
        # vanishes, but the axis survives in the symmetric part,
        # R + I = 2·n·nᵀ.  Take its largest column for numerical stability.
        sym = r_clean + np.eye(3)
        axis = sym[:, np.argmax(np.linalg.norm(sym, axis=0))]
        norm = np.linalg.norm(axis)

    axis /= norm
    if axis[2] < 0:
        axis = -axis
        sweep_deg = -sweep_deg
    return axis, sweep_deg


def _ignore_roll_axis(solves, sweep_deg, sigma_roll):
    """
    RA/Dec-only axis: the pole of the arc defined by the boresight directions
    of the first, middle, and last solve.  Roll is not used to find the axis,
    making this immune to systematic roll errors (e.g. camera flop).

    Returns (axis, roll_cost):
      axis      : unit vector with axis[2] >= 0, or None when the boresights
                  are (nearly) identical — the scope is pointing at the
                  mechanical axis and RA/Dec carry no rotation information,
                  so the axis is undetermined.
      roll_cost : roll-consistency check.  The axis and sweeps are fully
                  determined by the three RA/Dec positions (no free
                  parameters), so the roll residuals measure only how
                  consistent the roll observations are with the RA/Dec-derived
                  axis.  Expected ~1 under pure noise; nan if the prediction
                  fails.  sweep_deg (from the two-solve estimate) only orients
                  the axis so the sweeps keep the same sign.
    """
    mid = len(solves) // 2
    b1 = _boresight_vec(solves[0][0], solves[0][1])
    b2 = _boresight_vec(solves[mid][0], solves[mid][1])
    b3 = _boresight_vec(solves[-1][0], solves[-1][1])
    n = np.cross(b1 - b2, b2 - b3)
    nm = np.linalg.norm(n)
    if nm <= 1e-9:
        return None, float("nan")
    axis = n / nm
    if axis[2] < 0:
        axis = -axis

    obs = [(ra, dec, roll) for ra, dec, roll, _ in solves]
    bs = [_boresight_vec(o[0], o[1]) for o in obs]

    # Orient axis so sweeps have same sign as the two-solve sweep
    t1_pos = _signed_sweep_angle(axis, bs[0], bs[1])
    t1_neg = _signed_sweep_angle(-axis, bs[0], bs[1])
    n_ir = axis if abs(t1_pos - sweep_deg) < abs(t1_neg - sweep_deg) else -axis
    t1 = _signed_sweep_angle(n_ir, bs[0], bs[1])
    t2 = _signed_sweep_angle(n_ir, bs[1], bs[2])

    roll_cost = float("nan")
    try:
        ps = _predict_three_solves(n_ir, t1, t2, obs[0][0], obs[0][1], obs[0][2])
        roll_cost = sum(
            (_wrap180(p[2] - m[2]) / sigma_roll) ** 2 for p, m in zip(ps, obs)
        )
    except Exception:
        pass
    return axis, roll_cost


# ── Main function ─────────────────────────────────────────────────────────────


def get_platform_adjustments(
    solves,
    latitude,
    lst_deg,
    sigma_ra=1 / 60,
    sigma_dec=1 / 60,
    sigma_roll=11.4592 / 60,
    ignore_roll=False,
    observation_jyear=None,
):
    """
    Calculate polar-axis misalignment from two or three plate solves.

    Parameters
    ----------
    solves            : iterable of two or three (ra, dec, roll, timestamp) tuples
                        Each tuple is one plate solve:
                          ra        — Right Ascension in degrees
                          dec       — Declination in degrees
                          roll      — Camera roll in degrees
                          timestamp — Time of the solve in seconds (any epoch;
                                      only differences matter).
                        Solves are sorted by timestamp internally (ties keep
                        their input order).  Exactly two or three solves are
                        supported; three trigger the weighted optimisation.
                        The latest timestamp is the reference epoch: all
                        earlier RAs are advanced by their individual sidereal
                        drift to match it.  Dec and roll are unaffected.
    latitude          : float   Observer's geographic latitude in degrees.
    lst_deg           : float   Local Sidereal Time at the time of the *last*
                                solve, in degrees (0–360).
                                To convert from hours: lst_deg = lst_hours * 15.
    sigma_ra          : float   Expected 1-sigma RA noise in degrees (default 1').
                                Used only when three solves are given.
    sigma_dec         : float   Expected 1-sigma Dec noise in degrees (default 1').
                                Used only when three solves are given.
    sigma_roll        : float   Expected 1-sigma roll noise in degrees
                                (default 1/R where R = field radius in radians;
                                for a 10° field, R = 5° = 0.0873 rad giving
                                sigma_roll = 11.4592 x sigma_RA/Dec ≈ 11.46x).
                                Set higher to downweight roll relative to RA/Dec.
                                Used only when three solves are given.
    ignore_roll       : bool    If True and three solves are given, use
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

    # 1. Express every solve in the equatorial frame at the epoch of the
    #    last solve (precess to JNOW if requested, then sidereal drift).
    solves = _epoch_align_solves(solves, observation_jyear)

    # 2. Two-solve axis estimate from the first and last solve.
    #    Used as-is for two solves, and as the seed for the optimiser when
    #    three solves are provided.
    nan = float("nan")
    axis, sweep_deg = _two_solve_axis(solves[0], solves[-1])
    if axis is None:
        # No measurable rotation between the solves.
        return nan, nan, 0.0, nan, nan, nan
    if abs(sweep_deg) < MIN_SWEEP_DEG:
        # Same sign convention as the full-result sweep below.
        return nan, nan, -sweep_deg, nan, nan, nan

    axis_dec = np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0)))
    axis_ra = np.degrees(np.arctan2(axis[1], axis[0])) % 360.0

    # 3. If three solves are given, refine the axis.
    opt_cost = nan
    roll_cost = nan
    if len(solves) >= 3:
        if ignore_roll:
            axis, roll_cost = _ignore_roll_axis(solves, sweep_deg, sigma_roll)
            if axis is None:
                # Boresights are (nearly) identical — the scope is pointing at
                # the mechanical axis and RA/Dec carry no rotation information.
                # The roll-based two-solve estimate is exactly what the caller
                # asked to avoid, so the axis is undetermined.
                return nan, nan, -sweep_deg, nan, nan, nan
        else:
            obs = [(ra, dec, roll) for ra, dec, roll, _ in solves]
            axis, opt_cost = _refine_axis_three_solves(
                obs, axis, sigma_ra, sigma_dec, sigma_roll
            )
        axis_dec = np.degrees(np.arcsin(np.clip(axis[2], -1.0, 1.0)))
        axis_ra = np.degrees(np.arctan2(axis[1], axis[0])) % 360.0

    # 4. Convert the equatorial axis direction to physical mount errors,
    #    using LST to resolve the RA -> azimuth mapping.
    dAlt, dAz = axis_to_altaz_error(axis, latitude, lst_deg)

    # 5. Fit quality: sqrt(final_cost / n_obs) at the optimiser solution.
    #    Uses the cost at the actual solution parameters — no sweep re-estimation.
    #    For ignore_roll=True: roll-only cost at the best-fit sweep for the
    #    cross-product axis — measures roll consistency with the RA/Dec-derived
    #    axis, with expected value ~1 under pure noise.
    fit_quality = nan
    if len(solves) >= 3:
        if ignore_roll and np.isfinite(roll_cost):
            fit_quality = np.sqrt(roll_cost / len(solves))
        elif not ignore_roll:
            fit_quality = np.sqrt(opt_cost / len(solves))

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
        az = np.radians(dAz)
    else:
        # SH: S-end of axis at alt=|latitude|+dAlt, due South + dAz
        alt = np.radians(abs(latitude) + dAlt)
        az = np.radians(180.0 + dAz)

    # Horizontal → equatorial: altitude/azimuth of the axis → (Dec, HA) → RA
    dec_axis = np.arcsin(
        np.sin(lat) * np.sin(alt) + np.cos(lat) * np.cos(alt) * np.cos(az)
    )
    ha_axis = np.arctan2(
        -np.cos(alt) * np.sin(az),
        np.cos(lat) * np.sin(alt) - np.sin(lat) * np.cos(alt) * np.cos(az),
    )
    ra_axis = np.radians(lst_deg) - ha_axis  # RA = LST − HA

    cd = np.cos(dec_axis)
    axis = np.array([cd * np.cos(ra_axis), cd * np.sin(ra_axis), np.sin(dec_axis)])

    M1 = attitude_mat(ra1, dec1, roll1)
    # In the SH the axis points toward SCP (axis[2]<0). Following the stars
    # means rotating around the SCP axis positively, which is a negative
    # rotation around NCP. The sign of from_rotvec therefore stays consistent
    # with NH when we leave the sign as-is after the SH axis construction.
    sign = 1 if latitude < 0 else -1
    Rtrack = R.from_rotvec(np.radians(sign * sweep_deg) * axis).as_matrix()
    M2 = Rtrack @ M1

    return extract_plate_solve(M2)
