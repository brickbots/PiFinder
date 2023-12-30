import datetime
import pytz
import math
from skyfield.api import (
    wgs84,
    Loader,
    Star,
    Angle,
    position_of_radec,
    load_constellation_map,
)
from skyfield.magnitudelib import planetary_magnitude
import PiFinder.utils as utils
import json
import hashlib


class FastAltAz:
    """
    Adapted from example at:
    http://www.stargazing.net/kepler/altaz.html
    """

    def __init__(self, lat, lon, dt):
        self.lat = lat
        self.lon = lon
        self.dt = dt

        j2000 = datetime.datetime(2000, 1, 1, 12, 0, 0)
        utc_tz = pytz.timezone("UTC")
        j2000 = utc_tz.localize(j2000)
        _d = self.dt - j2000
        days_since_j2000 = _d.total_seconds() / 60 / 60 / 24

        dec_hours = self.dt.hour + (self.dt.minute / 60)

        lst = 100.46 + 0.985647 * days_since_j2000 + self.lon + 15 * dec_hours

        self.local_siderial_time = lst % 360

    def radec_to_altaz(self, ra, dec, alt_only=False):
        hour_angle = (self.local_siderial_time - ra) % 360

        _alt = math.sin(dec * math.pi / 180) * math.sin(
            self.lat * math.pi / 180
        ) + math.cos(dec * math.pi / 180) * math.cos(
            self.lat * math.pi / 180
        ) * math.cos(
            hour_angle * math.pi / 180
        )

        alt = math.asin(_alt) * 180 / math.pi
        if alt_only:
            return alt

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
    return degree, minute, round(second, 2)


def ra_to_hms(ra):
    if ra < 0.0:
        ra = ra + 360
    mm, hh = math.modf(ra / 15.0)
    _, mm = math.modf(mm * 60.0)
    ss = round(_ * 60.0)
    return hh, mm, ss


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
        self.observer_loc = None
        self.constellation_map = load_constellation_map()
        self.ts = load.timescale()

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
        set observing location
        """
        self.observer_loc = self.earth + wgs84.latlon(
            lat,
            lon,
            altitude,
        )
        self._set_planet_names()

    def altaz_to_radec(self, alt, az, dt):
        """
        returns the ra/dec of a specfic
        apparent alt/az at the given time
        """
        t = self.ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        a = observer.from_altaz(alt_degrees=alt, az_degrees=az)
        ra, dec, distance = a.radec(epoch=t)
        return ra._degrees, dec._degrees

    def radec_to_altaz(self, ra, dec, dt, atmos=True):
        """
        returns the apparent ALT/AZ of a specfic
        RA/DEC at the given time
        """
        t = self.ts.from_datetime(dt)

        observer = self.observer_loc.at(t)
        # logging.debug(f"radec_to_altaz: '{ra}' '{dec}' '{dt}'")
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )

        apparent = observer.observe(sky_pos).apparent()
        if atmos:
            alt, az, distance = apparent.altaz("standard")
        else:
            alt, az, distance = apparent.altaz()
        return alt.degrees, az.degrees

    def radec_to_constellation(self, ra, dec):
        """
        Take a ra/dec and return the constellation
        """
        sky_pos = position_of_radec(Angle(degrees=ra)._hours, dec)
        return self.constellation_map(sky_pos)

    def calc_planets(self):
        """Returns dictionary with all planet positions:
        {'SUN': {'radec': (279.05819685702846, -23.176809282384962),
                 'radec_pretty': ((18.0, 36.0, 14), (-23, 10, 36.51)),
                 'altaz': (1.667930045300066, 228.61434416619613)},
        }
        """
        t = self.ts.now()
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
            except ValueError as ve:
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


# Create a single instance of the skyfield utils
sf_utils = Skyfield_utils()
