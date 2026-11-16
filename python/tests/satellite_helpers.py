"""Data and helpers of the satellite tests. The fixtures are in conftest.py."""

import datetime
import json
import os
from pathlib import Path
from typing import Iterable, Optional

import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.satellites as satellites
from PiFinder.state import Location

SAT_DATA = Path(__file__).parent / "data" / "satellites"
ISS_NORAD = 25544
# The longest device text line: about 16 characters fit the 128 px screen.
DEVICE_LINE_CHARS = 16

# A geostationary satellite. Its inclination is 0.85 degrees.
GEO_TLE = """ASTRA 1KR
1 29055U 06012A   26316.93979443  .00000130  00000+0  00000+0 0  9998
2 29055   0.8523  82.1538 0003456 151.0788 176.1913  1.00270139 47187
"""


def iss_elements() -> satellites.SatElements:
    results, _errors = satellites.parse_elements((SAT_DATA / "25544.3le").read_text())
    return results[0]


# One day after the epoch of the fixture element set.
NOW = iss_elements().epoch + datetime.timedelta(days=1)


def system_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def make_old(path: Path, hours: float = 1.0) -> None:
    """Set the time of ``path`` to ``hours`` before the system clock."""
    when = system_now().timestamp() - hours * 3600.0
    os.utime(path, (when, when))


class SatSharedState:
    """The part of the shared state that the satellite code reads."""

    def __init__(self, dt: datetime.datetime):
        self.dt = dt
        self._location = Location(
            lat=50.85, lon=4.35, altitude=50.0, lock=True, timezone="Europe/Brussels"
        )

    def altaz_ready(self):
        return True

    def datetime(self):
        return self.dt

    def location(self):
        return self._location


class FakeDownloads:
    """Replaces the network. Writes the ISS set as the group file when
    ``success`` is set."""

    def __init__(self, success: bool = True):
        self.success = success
        self.groups: list[str] = []

    def __call__(self, group, directory=None, progress_callback=None):
        self.groups.append(group)
        if self.success:
            satellites.group_file(group, directory).write_text(
                (SAT_DATA / "25544.3le").read_text()
            )
        return satellites.DownloadResult(self.success, None, None)


def seed_groups(
    directory: Path,
    files: Iterable[str] = ("visual", "stations"),
    selected: Optional[Iterable[str]] = None,
) -> None:
    """Write the group files: the visual fixture for "visual", the ISS set
    for the others. With ``selected``, write the selection too."""
    directory.mkdir(parents=True, exist_ok=True)
    for group in files:
        source = "visual.tle" if group == "visual" else "25544.3le"
        satellites.group_file(group, directory).write_text(
            (SAT_DATA / source).read_text()
        )
    if selected is not None:
        satellites.selection_file(directory).write_text(
            json.dumps({"groups": list(selected)})
        )


def make_catalog(
    directory: Path,
    shared_state=None,
    sync_passes: bool = True,
    build: bool = True,
    **kwargs,
) -> satellite_catalog.SatelliteCatalog:
    """A catalog without threads. With ``sync_passes`` the pass worker runs
    in the calling thread, so a test sees the result. Without it no pass
    worker runs. With ``build`` the catalog builds its objects."""
    cat = satellite_catalog.SatelliteCatalog(
        shared_state if shared_state is not None else SatSharedState(NOW),
        data_directory=directory,
        start_threads=False,
        **kwargs,
    )
    cat._spawn_pass_worker = cat._run_pass_updates if sync_passes else lambda: None
    if build:
        cat.do_timed_task()
    return cat
