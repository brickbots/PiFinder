"""The CelesTrak groups that the user can select.

This module imports nothing heavy. The device menu reads the groups from here
at import time. ``PiFinder.satellites`` imports and re-exports these names.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CelestrakGroup:
    """A CelesTrak GP group that the user can select."""

    name: str  # the GROUP value of the CelesTrak URL
    label: str
    # A large group holds thousands of satellites. A Pi needs a long time to
    # predict their passes.
    large: bool = False
    # A short label for the device menu. An empty value means the label.
    short: str = ""

    @property
    def menu_label(self) -> str:
        """The label in the device menu. A large group has a "*" mark."""
        text = self.short or self.label
        return text + "*" if self.large else text


# The CelesTrak groups that the user can select. The names are the GROUP
# values of the CelesTrak GP page. The large groups are at the end. They are
# not selected by default. CelesTrak has no "noaa" and "goes" groups. Their
# satellites are in "weather".
AVAILABLE_GROUPS = (
    CelestrakGroup("visual", "Brightest"),
    CelestrakGroup("stations", "Space stations", short="Stations"),
    CelestrakGroup(
        "last-30-days", "Launched in the last 30 days", short="Last 30 days"
    ),
    CelestrakGroup("amateur", "Amateur radio", short="Amateur"),
    CelestrakGroup("cubesat", "CubeSats"),
    CelestrakGroup("education", "Education"),
    CelestrakGroup("engineering", "Engineering"),
    CelestrakGroup("science", "Science"),
    CelestrakGroup("geodetic", "Geodetic"),
    CelestrakGroup("weather", "Weather"),
    CelestrakGroup("resource", "Earth resources", short="Resources"),
    CelestrakGroup("planet", "Planet"),
    CelestrakGroup("spire", "Spire"),
    CelestrakGroup("radar", "Radar calibration", short="Radar cal."),
    CelestrakGroup("sarsat", "Search and rescue", short="SARSAT"),
    CelestrakGroup("military", "Military"),
    CelestrakGroup("iridium-NEXT", "Iridium NEXT", short="Iridium"),
    CelestrakGroup("gps-ops", "GPS"),
    CelestrakGroup("galileo", "Galileo"),
    CelestrakGroup("glo-ops", "GLONASS"),
    CelestrakGroup("beidou", "BeiDou"),
    CelestrakGroup("geo", "Geostationary", short="Geostat."),
    CelestrakGroup("oneweb", "OneWeb", large=True),
    CelestrakGroup("kuiper", "Kuiper", large=True),
    CelestrakGroup("starlink", "Starlink", large=True),
    CelestrakGroup("active", "All active satellites", large=True, short="All active"),
)
CELESTRAK_GROUPS = tuple(group.name for group in AVAILABLE_GROUPS)
GROUPS_BY_NAME = {group.name: group for group in AVAILABLE_GROUPS}
# The groups that a PiFinder without a stored selection uses.
DEFAULT_GROUPS = ("visual", "stations")
