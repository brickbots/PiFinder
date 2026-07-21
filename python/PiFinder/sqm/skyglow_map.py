"""Expected natural-sky diffuse background ("floor") for the radiometer.

At a dark site the median sky background the radiometer converts to SQM sits
above the true patch the reference meter reports, by a diffuse floor that a
zenith-pointed hand-held meter does not integrate the same way. Measured on
the imx462/HQ cross-calibration sweeps, that floor is real light through the
optics — not pedestal, dark current, amp glow, or self-light — and it varies
with where the telescope points and how low in the sky it looks.

This module predicts that floor from three natural components, each of which is
a genuine sky-brightness term (the pieces GAMBONS / Leinert 1998 combine into a
full natural-sky-brightness map):

  integrated starlight   depends on galactic latitude b (and longitude l): a
                         field into the Milky Way plane carries far more
                         unresolved starlight than one toward the pole. The
                         b-profile here is fitted to Gaia DR3 faint-star
                         (13 < G < 19) surface density sampled along l ~ 70:
                         an exponential in |b| with a ~19.5 deg scale height,
                         dropping ~20x from plane to pole.
  airglow                brightens toward the horizon as the van Rhijn
                         function of airmass (needs the pointing altitude,
                         hence an observer location + time).
  base                   the isotropic remainder (instrumental diffuse light,
                         zodiacal residual, extragalactic background).

The absolute scale is per camera: the sensitive, NIR-enhanced imx462 collects
~11x more of this red-rich diffuse light than the IR-cut HQ, which is why the
HQ reads much closer to the reference without any correction.

The correction is OPTIONAL and solve-gated: ``expected_floor`` returns ``None``
when no RA/Dec is available (unsolved frame), and the caller falls back to the
per-camera base floor. When an observer location/time is not supplied the
airglow term is dropped (zenith assumption) rather than guessed.

CALIBRATION STATUS: the per-camera scale constants are fitted from only three
dark sweeps (imx462) that confound galactic latitude with altitude, plus the
Gaia vertical profile. The *structure* is physical and the b-profile is
data-grounded; the absolute constants are provisional and want a calibration
campaign spanning |b| and altitude independently. Upgrade path: replace
``_integrated_starlight`` with a bundled all-sky GAMBONS/Gaia radiance map
looked up by (l, b).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

# Equatorial (ICRS) -> galactic rotation matrix, J2000.
_EQ2GAL = (
    (-0.0548755604, -0.8734370902, -0.4838350155),
    (0.4941094279, -0.4448296300, 0.7469822445),
    (-0.8676661490, -0.1980763734, 0.4559837762),
)

# Integrated-starlight vertical profile, fitted to Gaia DR3 faint-star flux
# (13 < G < 19, 0.3 deg cones) along l ~ 70: isl(|b|) = C + A*exp(-|b|/H).
_ISL_C = 0.000100
_ISL_A = 0.002662
_ISL_H_DEG = 19.5
_ISL_PLANE = _ISL_C + _ISL_A  # value at b = 0, used to normalise to 1.0

# Per-camera floor model (ADU/s):
#     floor = base + k_isl * isl_norm(l, b) + k_air * (van_rhijn(airmass) - 1)
# imx462 fitted to the three 2026-07-20 dark sweeps + the Gaia profile.
# HQ is provisional: its dark sweeps sit near the plane and cannot constrain
# the slope, so it carries a flat base only until a |b|-spread calibration.
_CAMERA_FLOOR = {
    "imx462": {"base": 27.2, "k_isl": 33.4, "k_air": 29.4},
    "imx290": {"base": 27.2, "k_isl": 33.4, "k_air": 29.4},  # shares imx462 optics
    "hq": {"base": 4.5, "k_isl": 0.0, "k_air": 0.0},
    "imx477": {"base": 4.5, "k_isl": 0.0, "k_air": 0.0},
}


def equatorial_to_galactic(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    """(l, b) in degrees for ICRS (ra, dec) in degrees; l in [0, 360)."""
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    v = (
        math.cos(dec) * math.cos(ra),
        math.cos(dec) * math.sin(ra),
        math.sin(dec),
    )
    g = tuple(sum(_EQ2GAL[i][j] * v[j] for j in range(3)) for i in range(3))
    b = math.degrees(math.asin(max(-1.0, min(1.0, g[2]))))
    gl = math.degrees(math.atan2(g[1], g[0])) % 360.0
    return gl, b


def _julian_date(when: datetime) -> float:
    when = when.astimezone(timezone.utc)
    y, m = when.year, when.month
    d = when.day + (when.hour + (when.minute + when.second / 60.0) / 60.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5
    )


def altitude_deg(
    ra_deg: float, dec_deg: float, lat_deg: float, lon_deg: float, when: datetime
) -> float:
    """Apparent altitude (deg) of (ra, dec) from (lat, lon) at UTC ``when``.

    lon_deg is positive east. Refraction is not applied (irrelevant to the
    airmass weighting at the altitudes SQM sweeps use).
    """
    jd = _julian_date(when)
    t = jd - 2451545.0
    gmst = (280.46061837 + 360.98564736629 * t) % 360.0
    lst = (gmst + lon_deg) % 360.0
    ha = math.radians((lst - ra_deg) % 360.0)
    dec, lat = math.radians(dec_deg), math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(
        ha
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def _airmass(alt_deg: float) -> float:
    """Plane-parallel airmass, floored at ~5 deg altitude."""
    return 1.0 / math.sin(math.radians(max(alt_deg, 5.0)))


def _van_rhijn(airmass: float) -> float:
    """Airglow brightness relative to zenith for a ~90 km emitting layer."""
    sin_z = math.sqrt(max(0.0, 1.0 - 1.0 / airmass**2))
    return 1.0 / math.sqrt(max(1e-6, 1.0 - 0.96 * sin_z**2))


def _integrated_starlight(l_deg: float, b_deg: float) -> float:
    """Integrated-starlight surface brightness, normalised to 1.0 at b = 0.

    Longitude dependence is not yet calibrated (all sampled fields sit near
    l ~ 70), so only the well-constrained |b| profile is applied.
    """
    isl = _ISL_C + _ISL_A * math.exp(-abs(b_deg) / _ISL_H_DEG)
    return isl / _ISL_PLANE


def expected_floor(
    ra_deg: Optional[float],
    dec_deg: Optional[float],
    camera_type: str,
    *,
    alt_deg: Optional[float] = None,
    when: Optional[datetime] = None,
    lat_deg: Optional[float] = None,
    lon_deg: Optional[float] = None,
) -> Optional[float]:
    """Predicted diffuse-background floor (ADU/s) for a solved pointing.

    Returns ``None`` when no RA/Dec is available (unsolved frame) so the caller
    falls back to the per-camera base floor.

    The airglow term needs the pointing altitude. Pass ``alt_deg`` directly
    (PiFinder knows it from the solve + IMU) or supply observer ``lat_deg`` /
    ``lon_deg`` / ``when`` to derive it. With neither, airglow is dropped
    (zenith assumption) rather than guessed.
    """
    cam = _CAMERA_FLOOR.get(camera_type)
    if cam is None:
        return None
    if ra_deg is None or dec_deg is None:
        return None
    gl, b = equatorial_to_galactic(ra_deg, dec_deg)
    floor = cam["base"] + cam["k_isl"] * _integrated_starlight(gl, b)
    if cam["k_air"]:
        if (
            alt_deg is None
            and lat_deg is not None
            and lon_deg is not None
            and when is not None
        ):
            alt_deg = altitude_deg(ra_deg, dec_deg, lat_deg, lon_deg, when)
        if alt_deg is not None:
            floor += cam["k_air"] * (_van_rhijn(_airmass(alt_deg)) - 1.0)
    return floor


def base_floor(camera_type: str) -> float:
    """Solve-independent fallback floor (ADU/s) when RA/Dec is unavailable."""
    cam = _CAMERA_FLOOR.get(camera_type)
    return cam["base"] if cam else 0.0
