from datetime import datetime
import pytz
import math
import numpy as np
from typing import Tuple, Optional
from skyfield.api import (
    wgs84,
    Loader,
    Star,
    Angle,
    position_of_radec,
    load_constellation_map,
)
from skyfield.constants import T0 as J2000, B1950
from skyfield.magnitudelib import planetary_magnitude
import PiFinder.utils as utils
import json
import hashlib
import logging

logger = logging.getLogger("Catalogs.calc_utils")


class FastAltAz:
    """
    Adapted from example at:
    http://www.stargazing.net/kepler/altaz.html
    """

    def __init__(self, lat, lon, dt):
        self.lat = lat
        self.lon = lon
        self.dt = dt

        j2000 = datetime(2000, 1, 1, 12, 0, 0)
        utc_tz = pytz.timezone("UTC")
        j2000 = utc_tz.localize(j2000)
        _d = self.dt - j2000
        days_since_j2000 = _d.total_seconds() / 60 / 60 / 24

        dec_hours = self.dt.hour + (self.dt.minute / 60)

        lst = 100.46 + 0.985647 * days_since_j2000 + self.lon + 15 * dec_hours

        self.local_siderial_time = lst % 360

    def radec_to_altaz(self, ra, dec, alt_only=False) -> Tuple[float, Optional[float]]:
        hour_angle = (self.local_siderial_time - ra) % 360

        _alt = math.sin(dec * math.pi / 180) * math.sin(
            self.lat * math.pi / 180
        ) + math.cos(dec * math.pi / 180) * math.cos(
            self.lat * math.pi / 180
        ) * math.cos(hour_angle * math.pi / 180)

        alt = math.asin(_alt) * 180 / math.pi
        if alt_only:
            return alt, None

        _az = (
            math.sin(dec * math.pi / 180)
            - math.sin(alt * math.pi / 180) * math.sin(self.lat * math.pi / 180)
        ) / (math.cos(alt * math.pi / 180) * math.cos(self.lat * math.pi / 180))

        _az = math.acos(_az) * 180 / math.pi

        if math.sin(hour_angle * math.pi / 180) < 0:
            az = _az
        else:
            az = 360 - _az
        return alt, az


def ra_to_deg(ra_h, ra_m, ra_s):
    ra_deg = ra_h
    if ra_m > 0:
        ra_deg += ra_m / 60
    if ra_s > 0:
        ra_deg += ra_s / 60 / 60
    ra_deg *= 15

    return ra_deg


def dec_to_deg(dec, dec_m, dec_s):
    dec_deg = abs(dec)

    if dec_m > 0:
        dec_deg += dec_m / 60
    if dec_s > 0:
        dec_deg += dec_s / 60 / 60
    if dec < 0:
        dec_deg *= -1

    return dec_deg


def dec_to_dms(dec):
    degree = int(dec)
    fractional_degree = abs(dec - degree)
    minute = int(fractional_degree * 60)
    second = (fractional_degree * 60 - minute) * 60
    return int(degree), int(minute), int(second)


def ra_to_hms(ra):
    if ra < 0.0:
        ra = ra + 360
    mm, hh = math.modf(ra / 15.0)
    _, mm = math.modf(mm * 60.0)
    ss = round(_ * 60.0)
    return int(hh), int(mm), int(ss)


def epoch_to_epoch(ep_from, ep_to, ra_hours, dec_deg):
    """
    Convert a (ra_h, dec_d) position from one epoch (e.g. 1991.25) to another (e.g. 2000.0)
    """
    # Load the ephemeris
    ts = sf_utils.ts
    from_epoch = ts.tt(jd=ep_from)
    to_epoch = ts.tt(jd=ep_to)
    _p = position_of_radec(ra_hours=ra_hours, dec_degrees=dec_deg, epoch=from_epoch)
    RA_h, Dec, _ = _p.radec(epoch=to_epoch)
    return RA_h, Dec


def b1950_to_j2000(ra_hours, dec_deg):
    """
    Convert B1950 to j2000
    """
    return epoch_to_epoch(B1950, J2000, ra_hours, dec_deg)


def aim_degrees(shared_state, mount_type, screen_direction, target):
    """
    Returns degrees in either
    az/alt or RA/DEC depending on mount type
    from current position
    to target
    """
    solution = shared_state.solution()
    location = shared_state.location()
    dt = shared_state.datetime()
    if location.lock and dt and solution:
        if mount_type == "Alt/Az":
            if solution["Alt"]:
                # We have position and time/date!
                sf_utils.set_location(
                    location.lat,
                    location.lon,
                    location.altitude,
                )
                target_alt, target_az = sf_utils.radec_to_altaz(
                    target.ra,
                    target.dec,
                    dt,
                )
                az_diff = target_az - solution["Az"]
                az_diff = (az_diff + 180) % 360 - 180
                if screen_direction in ["flat", "as_bloom"]:
                    az_diff *= -1

                alt_diff = target_alt - solution["Alt"]
                alt_diff = (alt_diff + 180) % 360 - 180

                return az_diff, alt_diff
        else:
            # EQ Mount type
            ra_diff = target.ra - solution["RA"]
            ra_diff = (ra_diff + 180) % 360 - 180  # Convert to -180 to +180

            dec_diff = target.dec - solution["Dec"]
            dec_diff = (dec_diff + 180) % 360 - 180

            return ra_diff, dec_diff
    return None, None


def calc_object_altitude(shared_state, obj) -> Optional[float]:
    solution = shared_state.solution()
    location = shared_state.location()
    dt = shared_state.datetime()
    if location and dt and solution:
        aa = FastAltAz(
            location.lat,
            location.lon,
            dt,
        )
        alt, _ = aa.radec_to_altaz(
            obj.ra,
            obj.dec,
            alt_only=True,
        )
        return alt

    return None


def hadec_to_pa(ha_deg, dec_deg, lat_deg):
    """
    Returns the parallactic angle of an object at (ha, dec) for an observer
    at latitude lat.

    The parallactic angle is the angle between the great circles between the
    zenith (Z) to the source (S) and the North Pole (P) to the source. By
    convention, the parallactic angle is measured from PS to ZS, positive
    towards East. The parallactic angle is negative when H < 0 and positive
    when H > 0. When At the meridian (i.e. H=0), the parallactic angle is 0
    when dec < latitude and +/-180 degrees when dec > latitude.

    INPUTS:
    ha_deg, dec_deg: Hour Angle (HA) and declination of the target [deg]
    lat_deg: Latitude of the observer [deg]

    RETURNS:
    pa_deg: Parallactic angle [deg]
    """
    ha = np.deg2rad(ha_deg)
    dec = np.deg2rad(dec_deg)
    lat = np.deg2rad(lat_deg)

    pa = np.arctan2(np.sin(ha), np.cos(dec) * np.tan(lat) - np.sin(dec) * np.cos(ha))

    return np.rad2deg(pa)  # Parallactic angle [deg]


def hadec_to_roll(ha_deg, dec_deg, lat_deg):
    """
    Returns the roll of a target at a given (HA, Dec) for and observer at
    latitude lat.

    The roll or the field rotation angle, as returned by the Tetra3 solver,
    describes how much the source (S) is rotated on the sky as seen by and
    the observer. The roll measures the same angle as the parallactic but
    measured with a different orientation. See hadec_to_pa() for explanation of
    the parallactic angle. The roll is positive for anti-clockwise rotation of
    ZS to PS when looking out towards the sky.

    INPUTS:
    ha_deg: Hour Angle (HA) of the target [deg]
    dec_deg: Declination of the target [deg]
    lat_deg: Latitude of the observer [deg]

    RETURNS:
    roll: Roll [deg]
    """
    pa_deg = hadec_to_pa(ha_deg, dec_deg, lat_deg)  # Calculate the parallactic angle

    if dec_deg <= lat_deg:
        roll_deg = -pa_deg
    else:
        roll_deg = -pa_deg + np.sign(ha_deg) * 180

    return roll_deg


def hash_dict(d):
    serialized_data = json.dumps(d, sort_keys=True).encode()
    return hashlib.sha256(serialized_data).hexdigest()


class Skyfield_utils:
    """
    Class to persist various
    expensive items that
    skyfield requires (ephemeris, constellations, etc)
    and provide useful util functions using them.
    """

    def __init__(self):
        load = Loader(utils.astro_data_dir)
        self.eph = load("de421.bsp")
        self.earth = self.eph["earth"]
        self.observer_loc = None  # Barycenter used to calculate the target pos
        self._observer_geoid = None  # To get geographic position (lat, long)
        self.constellation_map = load_constellation_map()
        self.ts = load.timescale()
        self._set_planet_names()

    def _set_planet_names(self):
        full_planet_names = [
            name[0]
            for index, name in self.eph.names().items()
            if name[0] != "EARTH" and "BARYCENTER" not in name[0]
        ]
        full_planet_names += [
            "JUPITER_BARYCENTER",
            "SATURN_BARYCENTER",
            "URANUS_BARYCENTER",
            "NEPTUNE_BARYCENTER",
            "PLUTO_BARYCENTER",
        ]
        self.planets = [self.eph[name] for name in full_planet_names]
        self.planet_names = []
        for name in full_planet_names:
            if "BARYCENTER" in name:
                name = name.replace("_BARYCENTER", "")
            self.planet_names.append(name)

    def set_location(self, lat, lon, altitude):
        """
        set observing location.
        lat, long are in degrees. altitude is in meters.
        """
        # Barycenter used to calculate the target position:
        self.observer_loc = self.earth + wgs84.latlon(lat, lon, altitude)
        # To get geographic position (e.g. latitude, longitude)
        # Note: We can't get this info from self.observer_loc
        self._observer_geoid = wgs84.latlon(lat, lon, altitude)

    def get_lat_lon_alt(self):
        """Returns the observer latitude & longitude in degrees"""
        return (
            self._observer_geoid.latitude.degrees,
            self._observer_geoid.longitude.degrees,
            self._observer_geoid.elevation.m,
        )

    def altaz_to_radec(self, alt, az, dt):
        """
        returns the ra/dec of a specfic
        apparent alt/az at the given time
        """
        t = self.ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        a = observer.from_altaz(alt_degrees=alt, az_degrees=az)
        ra, dec, _distance = a.radec(epoch=t)
        return ra._degrees, dec._degrees

    def radec_to_altaz(self, ra, dec, dt, atmos=True):
        """
        returns the apparent ALT/AZ of a specfic
        RA/DEC at the given time
        """
        t = self.ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        # Logger.debug("radec_to_altaz: '%f' '%f' '%f'", ra, dec, dt)
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )

        apparent = observer.observe(sky_pos).apparent()
        if atmos:
            alt, az, _distance = apparent.altaz("standard")
        else:
            alt, az, _distance = apparent.altaz()
        return alt.degrees, az.degrees

    def get_lst_hrs(self, dt):
        """
        Returns the local sidereal time in hrs.

        INPUTS:
        dt: Python datetime object (must be timezone-aware)

        RETURNS:
        lst_hrs: Local sidereal time [hrs]
        """
        t = self.ts.from_datetime(dt)
        return self._observer_geoid.lst_hours_at(t)  # LST in hrs

    def ra_to_ha(self, ra_deg, dt):
        """
        Converts RA (right ascension in deg) to HA (hour angle in deg) at time
        dt. Note that HA is in deg.

        INPUTS:
        ra_deg: Right asension [deg]
        dt: Python datetime object (must be timezone-aware)

        RETURNS:
        ha_deg: Hour angle [deg]
        """
        lst_hrs = self.get_lst_hrs(dt)
        ha_hrs = lst_hrs - (ra_deg * 12 / 180)  # ra converted to hrs
        ha_hrs = (ha_hrs + 12) % 24 - 12  # Unwrap to -12 to +12hrs

        return ha_hrs * 180 / 12  # Hour angle [deg]

    def radec_to_roll(self, ra_deg, dec_deg, dt):
        """
        Returns the roll (field rotation) of an object at (ra, dec) as
        seen from an observer at latitiude, lat and time, dt. See hadec_to_roll()
        for how 'roll' is defined.

        INPUTS:
        ra_deg:
        dec:
        dt:

        RETURNS:
        roll_deg: Roll angle [deg]
        """
        ha_deg = self.ra_to_ha(ra_deg, dt)  # Note that HA is in deg
        lat_deg = self._observer_geoid.latitude.degrees
        roll_deg = hadec_to_roll(ha_deg, dec_deg, lat_deg)

        return roll_deg  # roll angle [deg]

    def radec_to_constellation(self, ra, dec):
        """
        Take a ra/dec and return the constellation
        """
        sky_pos = position_of_radec(Angle(degrees=ra)._hours, dec)
        return self.constellation_map(sky_pos)

    def calc_planets(self, dt):
        """Returns dictionary with all planet positions:
        {'SUN': {'radec': (279.05819685702846, -23.176809282384962),
                 'radec_pretty': ((18.0, 36.0, 14), (-23, 10, 36.51)),
                 'altaz': (1.667930045300066, 228.61434416619613)},
        }
        """
        if not self.observer_loc:
            logger.warning("no observer location set")
            return {}
        t = self.ts.from_datetime(dt)
        observer = self.observer_loc.at(t)
        planet_dict = {}
        for name, planet in zip(self.planet_names, self.planets):
            astrometric = observer.observe(planet).apparent()
            ra, dec, _ = astrometric.radec()
            alt, az, _ = astrometric.altaz()
            ra_dec = (ra._degrees, dec.degrees)
            ra_dec_pretty = (ra_to_hms(ra._degrees), dec_to_dms(dec.degrees))
            alt_az = (alt.degrees, az.degrees)
            try:
                mag = float(planetary_magnitude(astrometric))
            except ValueError:
                mag = float("nan")
            if math.isnan(mag):
                mag = "?"
            else:
                mag = "%.2f" % mag

            if "BARYCENTER" in name:
                name = name.replace("_BARYCENTER", "")
            planet_dict[name] = {
                "radec": ra_dec,
                "radec_pretty": ra_dec_pretty,
                "altaz": alt_az,
                "mag": mag,
            }
        return planet_dict


sf_utils = Skyfield_utils()
