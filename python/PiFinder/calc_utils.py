import datetime
import pytz
import math
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
