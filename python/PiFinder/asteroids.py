"""MPC bright-asteroid elements, propagation, photometry, and apparitions."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from skyfield.data import mpc
from skyfield.data.spice import inertial_frames
from skyfield.timelib import julian_day

from PiFinder.calc_utils import sf_utils
from PiFinder.download_utils import (
    DownloadResult,
    check_download_needed,
    download_atomic,
)
from PiFinder.utils import Timer, asteroid_data_dir


logger = logging.getLogger("Asteroids")

MPC_BRIGHT_URL = (
    "https://minorplanetcenter.net/iau/Ephemerides/Bright/{year}/" "Soft00Bright.txt"
)
ASTEROID_VISIBLE_MAG_LIMIT = 15.0
APPARITION_SEARCH_DAYS = 550
OPPOSITION_MIN_ELONGATION_DEG = 170.0
_NUMBER_RE = re.compile(r"^\((\d+)\)(?:\s+(.*))?$")
_ECLIPTIC_TO_ICRF = inertial_frames["ECLIPJ2000"].T


def asteroid_file_for_year(year: int, directory: Path = asteroid_data_dir) -> Path:
    return directory / f"Soft00Bright-{year}.txt"


def asteroid_url_for_year(year: int) -> str:
    return MPC_BRIGHT_URL.format(year=year)


def _validate_asteroid_file(path: Path) -> None:
    with path.open("rb") as source:
        dataframe = mpc.load_mpcorb_dataframe(source)
    if dataframe.empty:
        raise ValueError("MPC bright-asteroid file contains no objects")
    if (
        dataframe["designation"]
        .map(lambda value: bool(_NUMBER_RE.match(str(value))))
        .sum()
        == 0
    ):
        raise ValueError("MPC bright-asteroid file has no numbered asteroids")


def download_asteroid_year(
    year: int,
    directory: Path = asteroid_data_dir,
    progress_callback: Optional[Callable[[Optional[int]], None]] = None,
) -> DownloadResult:
    return download_atomic(
        asteroid_url_for_year(year),
        asteroid_file_for_year(year, directory),
        progress_callback=progress_callback,
        validator=_validate_asteroid_file,
    )


def check_asteroid_download_needed(
    year: int, directory: Path = asteroid_data_dir
) -> tuple[bool, str]:
    return check_download_needed(
        asteroid_file_for_year(year, directory), asteroid_url_for_year(year)
    )


def available_element_files(
    dt: datetime, directory: Path = asteroid_data_dir
) -> list[Path]:
    """Newest useful annual files, including next year when MPC has published it."""
    years = (dt.year - 1, dt.year, dt.year + 1)
    return [
        asteroid_file_for_year(year, directory)
        for year in years
        if asteroid_file_for_year(year, directory).exists()
    ]


def load_asteroids_dataframe(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        with path.open("rb") as source:
            frames.append(mpc.load_mpcorb_dataframe(source))
    if not frames:
        return pd.DataFrame()
    dataframe = pd.concat(frames, ignore_index=True)
    numeric = (
        "magnitude_H",
        "magnitude_G",
        "mean_anomaly_degrees",
        "argument_of_perihelion_degrees",
        "longitude_of_ascending_node_degrees",
        "inclination_degrees",
        "eccentricity",
        "mean_daily_motion_degrees",
        "semimajor_axis_au",
    )
    for column in numeric:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
    dataframe["magnitude_G"] = dataframe["magnitude_G"].fillna(0.15)
    required = [column for column in numeric if column != "magnitude_G"] + [
        "epoch_packed",
        "designation",
    ]
    dataframe = dataframe.dropna(subset=required)
    dataframe = dataframe[
        (dataframe.eccentricity >= 0.0) & (dataframe.eccentricity < 1.0)
    ]
    dataframe["number"] = dataframe.designation.map(_minor_planet_number)
    dataframe = dataframe.dropna(subset=["number"])
    dataframe["number"] = dataframe.number.astype(int)
    # Lexical order of the MPC packed epoch is chronological within these
    # modern annual files. Prefer the freshest duplicate across year files.
    return (
        dataframe.sort_values("epoch_packed")
        .drop_duplicates(subset=["number"], keep="last")
        .sort_values("number")
        .reset_index(drop=True)
    )


def _minor_planet_number(designation: str) -> Optional[int]:
    match = _NUMBER_RE.match(str(designation).strip())
    return int(match.group(1)) if match else None


def minor_planet_name(designation: str) -> str:
    match = _NUMBER_RE.match(str(designation).strip())
    if not match:
        return str(designation).strip()
    return (match.group(2) or match.group(1)).strip()


def _packed_epoch_jd(value: str) -> float:
    def unpack(char: str) -> int:
        return ord(char) - (48 if char.isdigit() else 55)

    value = str(value)
    year = 100 * unpack(value[0]) + int(value[1:3])
    return julian_day(year, unpack(value[3]), unpack(value[4])) - 0.5


def _heliocentric_positions(dataframe: pd.DataFrame, tt_jd) -> np.ndarray:
    """Return heliocentric ICRF positions shaped ``(3, objects, times)``."""
    target_jd = np.atleast_1d(np.asarray(tt_jd, dtype=float))
    epoch_jd = np.asarray([_packed_epoch_jd(v) for v in dataframe.epoch_packed])
    mean_anomaly = np.radians(dataframe.mean_anomaly_degrees.to_numpy(float))[:, None]
    mean_motion = np.radians(dataframe.mean_daily_motion_degrees.to_numpy(float))[
        :, None
    ]
    anomaly = (
        mean_anomaly + mean_motion * (target_jd[None, :] - epoch_jd[:, None])
    ) % (2.0 * math.pi)
    eccentricity = dataframe.eccentricity.to_numpy(float)[:, None]

    eccentric_anomaly = anomaly.copy()
    for _ in range(12):
        correction = (
            eccentric_anomaly - eccentricity * np.sin(eccentric_anomaly) - anomaly
        ) / (1.0 - eccentricity * np.cos(eccentric_anomaly))
        eccentric_anomaly -= correction
        if np.max(np.abs(correction)) < 1e-13:
            break

    semimajor = dataframe.semimajor_axis_au.to_numpy(float)[:, None]
    x_orbit = semimajor * (np.cos(eccentric_anomaly) - eccentricity)
    y_orbit = semimajor * np.sqrt(1.0 - eccentricity**2) * np.sin(eccentric_anomaly)

    node = np.radians(dataframe.longitude_of_ascending_node_degrees.to_numpy(float))[
        :, None
    ]
    peri = np.radians(dataframe.argument_of_perihelion_degrees.to_numpy(float))[:, None]
    inc = np.radians(dataframe.inclination_degrees.to_numpy(float))[:, None]
    cos_node, sin_node = np.cos(node), np.sin(node)
    cos_peri, sin_peri = np.cos(peri), np.sin(peri)
    cos_inc, sin_inc = np.cos(inc), np.sin(inc)

    x = (cos_node * cos_peri - sin_node * sin_peri * cos_inc) * x_orbit + (
        -cos_node * sin_peri - sin_node * cos_peri * cos_inc
    ) * y_orbit
    y = (sin_node * cos_peri + cos_node * sin_peri * cos_inc) * x_orbit + (
        -sin_node * sin_peri + cos_node * cos_peri * cos_inc
    ) * y_orbit
    z = sin_peri * sin_inc * x_orbit + cos_peri * sin_inc * y_orbit
    return np.einsum("ij,jnt->int", _ECLIPTIC_TO_ICRF, np.array([x, y, z]))


def hg_magnitude(
    magnitude_h,
    magnitude_g,
    sun_distance,
    observer_distance,
    phase_angle_radians,
):
    """IAU H-G apparent visual magnitude model."""
    tan_half = np.tan(np.clip(phase_angle_radians, 0.0, math.pi - 1e-9) / 2.0)
    phi1 = np.exp(-3.33 * np.power(tan_half, 0.63))
    phi2 = np.exp(-1.87 * np.power(tan_half, 1.22))
    phase = (1.0 - magnitude_g) * phi1 + magnitude_g * phi2
    return (
        magnitude_h
        + 5.0 * np.log10(sun_distance * observer_distance)
        - 2.5 * np.log10(phase)
    )


def _geometry(dataframe: pd.DataFrame, times, observer_positions: np.ndarray):
    helio = _heliocentric_positions(dataframe, times.tt)
    sun = sf_utils.eph["sun"].at(times).position.au
    if sun.ndim == 1:
        sun = sun[:, None]
    observer = observer_positions
    if observer.ndim == 1:
        observer = observer[:, None]
    topocentric = sun[:, None, :] + helio - observer[:, None, :]
    earth_distance = np.linalg.norm(topocentric, axis=0)
    sun_distance = np.linalg.norm(helio, axis=0)
    asteroid_to_sun = -helio
    asteroid_to_observer = -topocentric
    cos_phase = np.sum(asteroid_to_sun * asteroid_to_observer, axis=0) / (
        sun_distance * earth_distance
    )
    phase_angle = np.arccos(np.clip(cos_phase, -1.0, 1.0))
    h = dataframe.magnitude_H.to_numpy(float)[:, None]
    g = dataframe.magnitude_G.to_numpy(float)[:, None]
    magnitude = hg_magnitude(h, g, sun_distance, earth_distance, phase_angle)
    return helio, topocentric, earth_distance, sun_distance, magnitude


def _radec(topocentric: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    eq_pos = np.einsum("ij,jnt->int", sf_utils.ts.J2000.M, topocentric)
    distance = np.linalg.norm(eq_pos, axis=0)
    ra = np.degrees(np.arctan2(eq_pos[1], eq_pos[0])) % 360.0
    dec = np.degrees(np.arcsin(np.clip(eq_pos[2] / distance, -1.0, 1.0)))
    return ra, dec


def _angular_motion_arcsec_per_hour(topocentric: np.ndarray) -> np.ndarray:
    """Return apparent one-hour sky motion for each object."""
    unit = topocentric / np.linalg.norm(topocentric, axis=0)[None, :, :]
    cos_separation = np.sum(unit[:, :, 0] * unit[:, :, 1], axis=0)
    return np.degrees(np.arccos(np.clip(cos_separation, -1.0, 1.0))) * 3600.0


def _next_apparition_index(separation: np.ndarray) -> tuple[int, bool]:
    """Return the first future local maximum, never the day-0 endpoint."""
    local_maxima = (
        np.nonzero(
            (separation[1:-1] >= separation[:-2]) & (separation[1:-1] >= separation[2:])
        )[0]
        + 1
    )
    opposition_candidates = local_maxima[
        separation[local_maxima] >= OPPOSITION_MIN_ELONGATION_DEG
    ]
    if len(opposition_candidates):
        return int(opposition_candidates[0]), True
    if len(local_maxima):
        return int(local_maxima[0]), False

    # A maximum can fall on the far scan boundary. Day 0 remains excluded: it
    # might be an event that passed minutes ago and is therefore not "next".
    future_index = int(np.nanargmax(separation[1:])) + 1
    return (
        future_index,
        bool(separation[future_index] >= OPPOSITION_MIN_ELONGATION_DEG),
    )


def _apparitions(dataframe: pd.DataFrame, dt: datetime) -> dict[int, dict[str, Any]]:
    start = sf_utils.ts.from_datetime(dt)
    times = sf_utils.ts.tt_jd(start.tt + np.arange(APPARITION_SEARCH_DAYS + 1))
    earth = sf_utils.earth.at(times).position.au
    _helio, geocentric, earth_distance, _sun_distance, magnitude = _geometry(
        dataframe, times, earth
    )
    sun = sf_utils.eph["sun"].at(times).position.au
    sun_from_earth = sun - earth
    cos_elongation = np.sum(geocentric * sun_from_earth[:, None, :], axis=0) / (
        earth_distance * np.linalg.norm(sun_from_earth, axis=0)[None, :]
    )
    elongation = np.degrees(np.arccos(np.clip(cos_elongation, -1.0, 1.0)))
    # Opposition is a 180-degree *ecliptic-longitude* separation. Its true
    # angular elongation can be noticeably smaller for high-latitude objects.
    to_ecliptic = _ECLIPTIC_TO_ICRF.T
    asteroid_ecliptic = np.einsum("ij,jnt->int", to_ecliptic, geocentric)
    sun_ecliptic = to_ecliptic @ sun_from_earth
    asteroid_lon = np.degrees(np.arctan2(asteroid_ecliptic[1], asteroid_ecliptic[0]))
    sun_lon = np.degrees(np.arctan2(sun_ecliptic[1], sun_ecliptic[0]))[None, :]
    longitude_separation = np.abs((asteroid_lon - sun_lon + 180.0) % 360.0 - 180.0)

    result: dict[int, dict[str, Any]] = {}
    datetimes = times.utc_datetime()
    for row_index, number in enumerate(dataframe.number.to_numpy(int)):
        separation = longitude_separation[row_index]
        opposition_index, is_opposition = _next_apparition_index(separation)
        # Keep peak brightness tied to this apparition instead of selecting a
        # second, brighter opposition near the far edge of the 18-month scan.
        peak_start = max(0, opposition_index - 90)
        peak_stop = min(len(times), opposition_index + 91)
        peak_index = peak_start + int(
            np.nanargmin(magnitude[row_index, peak_start:peak_stop])
        )
        maximum_elongation = float(elongation[row_index, opposition_index])
        result[number] = {
            "opposition_date": datetimes[opposition_index].date(),
            "opposition_kind": "Opposition" if is_opposition else "Greatest elongation",
            "maximum_elongation_deg": maximum_elongation,
            "peak_date": datetimes[peak_index].date(),
            "peak_magnitude": float(magnitude[row_index, peak_index]),
        }
    return result


def process_asteroid(row, dt: datetime) -> dict[str, Any]:
    dataframe = pd.DataFrame([row])
    result = _calculate_dataframe(dataframe, dt, include_apparitions=False)
    return next(iter(result.values()), {})


def _calculate_dataframe(
    dataframe: pd.DataFrame,
    dt: datetime,
    include_apparitions: bool = True,
) -> dict[int, dict[str, Any]]:
    if dataframe.empty:
        return {}
    time = sf_utils.ts.from_datetime(dt)
    motion_times = sf_utils.ts.tt_jd(np.array([time.tt, time.tt + 1.0 / 24.0]))
    observer = sf_utils.observer_loc.at(motion_times).position.au
    _, topocentric, earth_distance, sun_distance, magnitude = _geometry(
        dataframe, motion_times, observer
    )
    angular_motion = _angular_motion_arcsec_per_hour(topocentric)
    ra, dec = _radec(topocentric)
    visible = np.isfinite(magnitude[:, 0]) & (
        magnitude[:, 0] <= ASTEROID_VISIBLE_MAG_LIMIT
    )
    visible_df = dataframe.loc[visible].reset_index(drop=True)
    apparitions = (
        _apparitions(visible_df, dt) if include_apparitions and len(visible_df) else {}
    )

    result: dict[int, dict[str, Any]] = {}
    for source_index in np.nonzero(visible)[0]:
        row = dataframe.iloc[source_index]
        number = int(row.number)
        item = {
            "number": number,
            "name": minor_planet_name(row.designation),
            "full_name": str(row.designation).strip(),
            "radec": (float(ra[source_index, 0]), float(dec[source_index, 0])),
            "mag": float(magnitude[source_index, 0]),
            "earth_distance": float(earth_distance[source_index, 0]),
            "sun_distance": float(sun_distance[source_index, 0]),
            "angular_motion_arcsec_per_hour": float(angular_motion[source_index]),
        }
        item.update(apparitions.get(number, {}))
        result[number] = item
    return result


def calc_asteroids(
    dt: datetime,
    paths: Optional[list[Path]] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> dict[int, dict[str, Any]]:
    with Timer("calc_asteroids()"):
        if sf_utils.observer_loc is None or dt is None:
            return {}
        if progress_callback:
            progress_callback(0)
        dataframe = load_asteroids_dataframe(paths or available_element_files(dt))
        if progress_callback:
            progress_callback(10)
        if dataframe.empty:
            return {}
        try:
            result = _calculate_dataframe(dataframe, dt)
        except Exception:
            logger.error(
                "VECTORIZED ASTEROID PROPAGATION FAILED — using per-object fallback",
                exc_info=True,
            )
            result = {}
            total = len(dataframe)
            for index, (_, row) in enumerate(dataframe.iterrows(), 1):
                try:
                    item = process_asteroid(row, dt)
                except Exception as exc:
                    logger.warning("Skipping asteroid %s: %s", row.designation, exc)
                    continue
                if item:
                    result[int(item["number"])] = item
                if progress_callback:
                    progress_callback(10 + int(90 * index / total))
        if progress_callback:
            progress_callback(100)
        return result
