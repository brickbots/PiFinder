from typing import Dict, Any, Tuple, Optional, Callable
from datetime import datetime, timezone
from skyfield.data import mpc
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from PiFinder.utils import Timer, comet_file
from PiFinder.calc_utils import sf_utils
from PiFinder import timez
import numpy as np
import pandas as pd
import requests
import os
import logging
import math

logger = logging.getLogger("Comets")


def process_comet(comet_data, dt) -> Dict[str, Any]:
    name, row = comet_data
    t = sf_utils.ts.from_datetime(dt)
    sun = sf_utils.eph["sun"]
    comet = sun + mpc.comet_orbit(row, sf_utils.ts, GM_SUN)

    # print(f"Processing comet: {name}, {sf_utils.observer_loc}")
    topocentric = (comet - sf_utils.observer_loc).at(t)
    heliocentric = (comet - sun).at(t)

    ra, dec, earth_distance = topocentric.radec(sf_utils.ts.J2000)
    sun_distance = heliocentric.radec(sf_utils.ts.J2000)[2]

    mag_g = float(row["magnitude_g"])
    mag_k = float(row["magnitude_k"])
    mag = (
        mag_g
        + 2.5 * mag_k * math.log10(sun_distance.au)
        + 5.0 * math.log10(earth_distance.au)
    )
    if mag > 15:
        logger.debug(f"Filtering out {name}: mag={mag:.1f} (too dim)")
        return {}

    logger.debug(f"Including {name}: mag={mag:.1f}")

    ra_dec = (ra._degrees, dec.degrees)
    # alt, az = sf_utils.radec_to_altaz(ra._degrees, dec.degrees, dt, atmos=False)
    # ra_dec_pretty = (ra_to_hms(ra._degrees), dec_to_dms(dec.degrees))
    # alt_az = (alt, az)

    return {
        "name": name,
        "radec": ra_dec,
        "mag": mag,
        "earth_distance": earth_distance.au,
        "sun_distance": sun_distance.au,
    }


def check_if_comet_download_needed(
    local_filename, url=mpc.COMET_URL, timeout=5
) -> Tuple[bool, str]:
    """
    Check if comet data download is needed by comparing local file with remote.

    Args:
        local_filename: Path to local file
        url: URL to check
        timeout: Request timeout in seconds

    Returns:
        Tuple of (need_download: bool, reason: str)
    """
    if not os.path.exists(local_filename):
        return (True, "no existing file")

    try:
        # Send a HEAD request to get headers without downloading
        response = requests.head(url, timeout=timeout)
        response.raise_for_status()

        last_modified = response.headers.get("Last-Modified")
        if not last_modified:
            return (False, "cannot verify remote date")

        remote_date = datetime.strptime(
            last_modified, "%a, %d %b %Y %H:%M:%S GMT"
        ).replace(tzinfo=timezone.utc)

        local_date = timez.utc_from_timestamp(os.path.getmtime(local_filename))

        if remote_date > local_date:
            age_diff = (remote_date - local_date).total_seconds() / 86400
            return (True, f"file outdated by {age_diff:.1f} days")
        else:
            return (False, "file is up to date")

    except requests.RequestException as e:
        logger.warning(f"Could not check remote file: {e}")
        return (False, f"network error: {e}")


def comet_data_download(
    local_filename,
    url=mpc.COMET_URL,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Download comet data from the Minor Planet Center.

    Args:
        local_filename: Path to save the downloaded file
        url: URL to download from
        progress_callback: Optional callback function that receives progress percentage (0-100)

    Returns:
        Tuple of (success: bool, age_in_days: Optional[float], file_mtime: Optional[float])
        file_mtime is the file's modification time as a timestamp (for caching)
    """
    try:
        now = datetime.now(timezone.utc)

        logger.debug("Downloading comet data...")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Get file size for progress calculation
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(local_filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Report progress if callback provided and total size known
                    if progress_callback and total_size > 0:
                        progress = int((downloaded / total_size) * 100)
                        progress_callback(progress)

        # Try to get Last-Modified to set file mtime
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            remote_date = datetime.strptime(
                last_modified, "%a, %d %b %Y %H:%M:%S GMT"
            ).replace(tzinfo=timezone.utc)
            file_mtime = remote_date.timestamp()
            os.utime(local_filename, (file_mtime, file_mtime))
            age_days = (now - remote_date).total_seconds() / 86400
        else:
            file_mtime = os.path.getmtime(local_filename)
            age_days = None

        logger.debug("File downloaded successfully.")
        if progress_callback:
            progress_callback(100)
        return True, age_days, file_mtime

    except requests.RequestException as e:
        logger.error(f"Error downloading comet data: {e}")
        return False, None, None


def _load_comets_dataframe() -> pd.DataFrame:
    """Load and clean the MPC comet-elements file into a dataframe.

    Coerces orbital-element columns to numeric (MPC data occasionally
    contains rows Skyfield's parser leaves as strings, which would poison
    the whole column), drops rows missing essential elements, and keeps the
    most recent orbit solution per designation.
    """
    with open(comet_file, "rb") as f:
        comets_df = mpc.load_comets_dataframe(f)

    # Ensure orbital element columns are numeric — MPC data sometimes
    # contains rows that Skyfield's parser can't handle (e.g. MPEC
    # 2026-F34 historical comets), which causes the entire column to
    # become dtype=object (strings).  Skyfield's comet_orbit() then
    # crashes on every comet with a numpy UFuncNoLoopError.
    numeric_cols = [
        "perihelion_year",
        "perihelion_month",
        "perihelion_day",
        "argument_of_perihelion_degrees",
        "longitude_of_ascending_node_degrees",
        "inclination_degrees",
        "eccentricity",
        "perihelion_distance_au",
        "magnitude_g",
        "magnitude_k",
    ]
    for col in numeric_cols:
        if col in comets_df.columns:
            comets_df[col] = pd.to_numeric(comets_df[col], errors="coerce")

    # Drop rows where essential orbital elements couldn't be parsed
    essential = [
        "perihelion_year",
        "perihelion_month",
        "perihelion_day",
        "eccentricity",
        "perihelion_distance_au",
    ]
    comets_df = comets_df.dropna(
        subset=[c for c in essential if c in comets_df.columns]
    )

    comets_df = (
        comets_df.sort_values("reference")
        .groupby("designation", as_index=False)
        .last()
        .set_index("designation", drop=False)
    )

    # groupby/last can coerce numeric columns to strings when NaN values
    # are present; ensure perihelion date fields are numeric before use
    for col in ("perihelion_year", "perihelion_month", "perihelion_day"):
        comets_df[col] = pd.to_numeric(comets_df[col], errors="coerce")
    comets_df = comets_df.dropna(
        subset=["perihelion_year", "perihelion_month", "perihelion_day"]
    )

    return comets_df


def _calc_comets_vectorized(comets_df: pd.DataFrame, dt) -> Dict[str, Any]:
    """Compute every comet's position in a single batched propagation.

    Skyfield's Kepler ``propagate()`` is array-aware, so all comets are
    advanced to time ``dt`` in one numpy call instead of the old per-comet
    Python loop (957 comets x 2 skyfield propagations each).  That loop took
    tens of seconds of pure-Python skyfield (which holds the GIL), and the
    comet thread re-ran it far more often than the data changes, so it pegged
    a CPU core continuously whenever PiFinder was locked on a target and
    starved the UI loop (commit 4aafd89a regressed an incremental update to
    this full reinit; see comet_catalog.py / catalog_base.py TimerMixin for
    the 5 s-while-uninitialised timer + _task_lock requeue that made it run
    back-to-back).

    RA/Dec are referred to the mean equator and equinox of J2000, matching
    the old per-comet ``radec(ts.J2000)`` call to floating-point precision
    (verified against the per-comet path in tests/test_comets.py).  The
    magnitude cut reproduces the old ``if mag > 15`` test exactly, including
    its quirk of keeping comets whose magnitude is NaN (``nan > 15`` is
    False).
    """
    if comets_df.empty:  # self-safe; calc_comets also guards before calling
        return {}
    t = sf_utils.ts.from_datetime(dt)

    # One batched KeplerOrbit covering every comet (Skyfield's vectorized
    # builder), propagated in a single call -> heliocentric state, AU,
    # equatorial ICRF, relative to the Sun.
    kepler = mpc._comet_orbits(comets_df, sf_utils.ts, GM_SUN)
    helio_pos = kepler._at(t)[0]
    if helio_pos.ndim == 1:  # propagate() squeezes a single comet to (3,)
        helio_pos = helio_pos[:, np.newaxis]

    # Sun and observer are single 3-vectors relative to the solar-system
    # barycentre; broadcast them across all comets.  topocentric = observer
    # -> comet, heliocentric = Sun -> comet (matches the old VectorSum math).
    sun_pos = sf_utils.eph["sun"].at(t).position.au
    observer_pos = sf_utils.observer_loc.at(t).position.au
    topo_pos = sun_pos[:, np.newaxis] + helio_pos - observer_pos[:, np.newaxis]

    earth_distance = np.linalg.norm(topo_pos, axis=0)
    sun_distance = np.linalg.norm(helio_pos, axis=0)

    # Reproduce skyfield's radec(ts.J2000): it rotates the ICRF position by
    # the epoch precession matrix (epoch.M) then converts to spherical.  We
    # apply the same constant (3,3) rotation to the whole (3,N) array at once.
    # M is orthonormal, so it preserves earth_distance (used for the arcsin).
    eq_pos = sf_utils.ts.J2000.M @ topo_pos
    ra_deg = np.degrees(np.arctan2(eq_pos[1], eq_pos[0])) % 360.0
    dec_deg = np.degrees(np.arcsin(np.clip(eq_pos[2] / earth_distance, -1.0, 1.0)))

    mag_g = comets_df["magnitude_g"].to_numpy(dtype=float)
    mag_k = comets_df["magnitude_k"].to_numpy(dtype=float)
    mag = mag_g + 2.5 * mag_k * np.log10(sun_distance) + 5.0 * np.log10(earth_distance)

    names = comets_df["designation"].to_numpy()

    # Keep comets that are NOT dimmer than mag 15.  Phrased as ~(mag > 15)
    # rather than (mag <= 15) so NaN magnitudes are kept, matching the old
    # per-comet filter.
    comet_dict: Dict[str, Any] = {}
    for i in np.nonzero(~(mag > 15))[0]:
        name = str(names[i])
        comet_dict[name] = {
            "name": name,
            "radec": (float(ra_deg[i]), float(dec_deg[i])),
            "mag": float(mag[i]),
            "earth_distance": float(earth_distance[i]),
            "sun_distance": float(sun_distance[i]),
        }
    return comet_dict


def _calc_comets_per_comet(
    comets_df: pd.DataFrame,
    dt,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    """Per-comet fallback path (the original loop).

    Slow — one Python skyfield propagation per comet — but tolerant of a
    single bad row, so it backstops the vectorized path if a future Skyfield
    release or a malformed MPC row ever breaks the batched call.  Also serves
    as the reference oracle in tests.
    """
    comet_dict: Dict[str, Any] = {}
    comet_data = list(comets_df.iterrows())
    total_comets = len(comet_data)
    processed = 0

    for comet in comet_data:
        try:
            result = process_comet(comet, dt)
        except Exception as e:
            logger.warning(f"Skipping comet {comet[0]}: {e}")
            result = {}
        if result:
            comet_dict[result["name"]] = result

        processed += 1
        if progress_callback and total_comets > 0:
            progress_callback(int((processed / total_comets) * 100))

    return comet_dict


def calc_comets(
    dt, comet_names=None, progress_callback: Optional[Callable[[int], None]] = None
) -> dict:
    """
    Calculate comet positions.

    Args:
        dt: Datetime for calculations
        comet_names: Optional list of specific comet names to calculate
        progress_callback: Optional callback function that receives progress percentage (0-100)

    Returns:
        Dict of comet data keyed by comet name
    """
    with Timer("calc_comets()"):
        comet_dict: Dict[str, Any] = {}
        if sf_utils.observer_loc is None or dt is None:
            return comet_dict

        # Report 0% at start (before slow file loading/processing)
        if progress_callback:
            progress_callback(0)

        comets_df = _load_comets_dataframe()

        if comet_names is not None:
            comets_df = comets_df[comets_df["designation"].isin(comet_names)]

        # Report progress after file loading + pandas processing
        if progress_callback:
            progress_callback(2)

        if len(comets_df) == 0:
            return comet_dict

        try:
            comet_dict = _calc_comets_vectorized(comets_df, dt)
        except Exception:
            # The batched call shouldn't fail with pinned Skyfield + curated
            # MPC data (a unit test guards this), but if it ever does, fall
            # back to the slower-but-tolerant per-comet path rather than
            # dropping all comets.  Log loudly (error + traceback): this path
            # silently burns ~minute-scale CPU every cycle, and the Comets
            # logger inherits root=ERROR so a warning here would be suppressed.
            logger.error(
                "VECTORIZED COMET PROPAGATION FAILED — using slow per-comet "
                "fallback (this is the CPU-hog path; investigate)",
                exc_info=True,
            )
            comet_dict = _calc_comets_per_comet(comets_df, dt, progress_callback)

        if progress_callback:
            progress_callback(100)

        return comet_dict
