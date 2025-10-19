from typing import Dict, Any, Tuple, Optional, Callable
from datetime import datetime, timezone
from skyfield.data import mpc
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from PiFinder.utils import Timer, comet_file
from PiFinder.calc_utils import sf_utils
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
        "orbital_elements": None,  # could add this later
        "row": row,
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

        local_date = datetime.fromtimestamp(
            os.path.getmtime(local_filename)
        ).replace(tzinfo=timezone.utc)

        if remote_date > local_date:
            age_diff = (remote_date - local_date).total_seconds() / 86400
            return (True, f"file outdated by {age_diff:.1f} days")
        else:
            return (False, "file is up to date")

    except requests.RequestException as e:
        logger.warning(f"Could not check remote file: {e}")
        return (False, f"network error: {e}")


def comet_data_download(
    local_filename, url=mpc.COMET_URL, progress_callback: Optional[Callable[[int], None]] = None
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
        total_size = int(response.headers.get('content-length', 0))
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


def calc_comets(dt, comet_names=None, progress_callback: Optional[Callable[[int], None]] = None) -> dict:
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

        with open(comet_file, "rb") as f:
            comets_df = mpc.load_comets_dataframe(f)

        # Report progress after file loading (roughly 33% of setup time)
        if progress_callback:
            progress_callback(1)

        comets_df = (
            comets_df.sort_values("reference")
            .groupby("designation", as_index=False)
            .last()
            .set_index("designation", drop=False)
        )

        # Report progress after pandas processing (roughly 66% of setup time)
        if progress_callback:
            progress_callback(2)

        comet_data = list(comets_df.iterrows())
        total_comets = len(comet_data)
        processed = 0

        for comet in comet_data:
            if comet_names is None or comet[0] in comet_names:
                result = process_comet(comet, dt)
                if result:
                    comet_dict[result["name"]] = result

            # Report progress
            processed += 1
            if progress_callback and total_comets > 0:
                progress = int((processed / total_comets) * 100)
                progress_callback(progress)

        return comet_dict
