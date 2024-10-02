from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timezone
from skyfield.data import mpc
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.elementslib import osculating_elements_of
from PiFinder.utils import Timer, comet_file
from PiFinder.calc_utils import sf_utils, ra_to_hms, dec_to_dms
import requests
import os
import logging
import math

logger = logging.getLogger("Comets")


def process_comet(comet_data, dt) -> Dict[str, Any]:
    name, row = comet_data
    t = sf_utils.ts.from_datetime(dt)
    sun = sf_utils.eph['sun']
    comet = sun + mpc.comet_orbit(row, sf_utils.ts, GM_SUN)

    # print(f"Processing comet: {name}, {sf_utils.observer_loc}")
    topocentric = (comet - sf_utils.observer_loc).at(t)
    heliocentric = (comet - sun).at(t)

    ra, dec, earth_distance = topocentric.radec(sf_utils.ts.J2000)
    sun_distance = heliocentric.radec(sf_utils.ts.J2000)[2]

    mag_g = float(row['magnitude_g'])
    mag_k = float(row['magnitude_k'])
    mag = mag_g + 2.5 * mag_k * math.log10(sun_distance.au) + \
        5.0 * math.log10(earth_distance.au)
    if mag > 15:
        return {}

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
        "row": row
    }


def comet_data_download(local_filename, url=mpc.COMET_URL) -> Tuple[bool, Optional[float]]:
    """
    Download the latest comet data from the Minor Planet Center.
    Return values are succes and the age of the file in days, if available.
    """
    try:
        now = datetime.now(timezone.utc)

        # Send a HEAD request to get headers without downloading the entire file
        response = requests.head(url)
        response.raise_for_status()  # Raise an exception for bad responses

        # Try to get the Last-Modified header
        last_modified = response.headers.get('Last-Modified')

        if last_modified:
            remote_date = datetime.strptime(last_modified, '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc)
            logger.debug(f"Remote Last-Modified: {remote_date}")

            # Check if local file exists and its modification time
            if os.path.exists(local_filename):
                local_date = datetime.fromtimestamp(os.path.getmtime(local_filename)).replace(tzinfo=timezone.utc)
                logger.debug(f"Local Last-Modified: {local_date}")

                if remote_date <= local_date:
                    logger.debug("Local file is up to date. No download needed.")
                    return True, round((now - local_date).days)

            # Download the file if it's new or doesn't exist locally
            logger.debug("Downloading new file...")
            response = requests.get(url)
            response.raise_for_status()

            with open(local_filename, 'wb') as f:
                f.write(response.content)

            # Set the file's modification time to match the server's last-modified time
            os.utime(local_filename, (remote_date.timestamp(), remote_date.timestamp()))

            logger.debug("File downloaded successfully.")
            return True, round((now - remote_date).days)
        else:
            logger.debug("Last-Modified header not available. Downloading file...")
            response = requests.get(url)
            response.raise_for_status()

            with open(local_filename, 'wb') as f:
                f.write(response.content)

            logger.debug("File downloaded successfully.")
            return True, None

    except requests.RequestException as e:
        logger.error(f"Error downloading comet data: {e}")
        return False, None


def calc_comets(dt, comet_names=None) -> dict:
    with Timer("calc_comets()"):
        comet_dict: Dict[str, Any] = {}
        if sf_utils.observer_loc is None or dt is None:
            logger.debug(f"calc_comets can't run: observer loc is None: {sf_utils.observer_loc is None}, dt is None: {dt is None}")
            return comet_dict

        with open(comet_file, "rb") as f:
            comets_df = mpc.load_comets_dataframe(f)

        comets_df = (comets_df.sort_values('reference')
                     .groupby('designation', as_index=False).last()
                     .set_index('designation', drop=False))

        comet_data = list(comets_df.iterrows())

        for comet in comet_data:
            if comet_names is None or comet[0] in comet_names:
                result = process_comet(comet, dt)
                if result:
                    comet_dict[result["name"]] = result
        return comet_dict
