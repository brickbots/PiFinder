"""
Unit tests for ``get_chart_rotation_angle`` and the orientation result it
returns. The function decides what "up" the chart shows, and flags
``is_fallback=True`` when the user selected a GPS-dependent mode but no
location lock is available yet (see issue #419).
"""

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.state import Location
from PiFinder.ui.chart import ChartOrientation, get_chart_rotation_angle


def _no_gps():
    return Location(lat=0.0, lon=0.0, altitude=0.0, lock=False)


def _gps_at(lat, lon=0.0, altitude=0.0):
    return Location(lat=lat, lon=lon, altitude=altitude, lock=True)


@pytest.mark.unit
class TestGetChartRotationAngle:
    def test_returns_none_when_radec_missing(self):
        assert get_chart_rotation_angle(None, 0.0, "eq_north_up") is None
        assert get_chart_rotation_angle(0.0, None, "eq_north_up") is None

    def test_eq_north_up_is_explicit_ncp(self):
        result = get_chart_rotation_angle(10.0, 20.0, "eq_north_up")
        assert result == ChartOrientation(0.0, "NCP", False)

    def test_eq_south_up_is_explicit_scp(self):
        result = get_chart_rotation_angle(10.0, 20.0, "eq_south_up")
        assert result == ChartOrientation(180.0, "SCP", False)

    def test_eq_auto_northern_with_gps(self):
        result = get_chart_rotation_angle(
            10.0, 20.0, "eq_auto", location=_gps_at(lat=45.0)
        )
        assert result == ChartOrientation(0.0, "NCP", False)

    def test_eq_auto_southern_with_gps(self):
        result = get_chart_rotation_angle(
            10.0, 20.0, "eq_auto", location=_gps_at(lat=-33.0)
        )
        assert result == ChartOrientation(180.0, "SCP", False)

    def test_eq_auto_no_gps_falls_back_to_ncp(self):
        # No location lock yet: northern-hemisphere default, but flagged.
        result = get_chart_rotation_angle(10.0, 20.0, "eq_auto", location=_no_gps())
        assert result == ChartOrientation(0.0, "NCP", True)

    def test_eq_auto_lockless_location_object_is_fallback(self):
        # A Location with lock=False should be treated the same as missing.
        result = get_chart_rotation_angle(
            10.0, 20.0, "eq_auto", location=_no_gps(), dt=None
        )
        assert result.is_fallback is True

    def test_horiz_no_gps_falls_back_to_ncp(self):
        result = get_chart_rotation_angle(
            10.0, 20.0, "horiz", location=_no_gps(), dt=None
        )
        assert result == ChartOrientation(0.0, "NCP", True)

    def test_horiz_with_gps_no_datetime_falls_back(self):
        # Locked location but no datetime: still a fallback because parallactic
        # angle needs both.
        result = get_chart_rotation_angle(
            10.0, 20.0, "horiz", location=_gps_at(lat=45.0), dt=None
        )
        assert result == ChartOrientation(0.0, "NCP", True)

    def test_horiz_with_gps_and_datetime_is_zenith(self):
        import datetime as _dt

        result = get_chart_rotation_angle(
            10.0,
            20.0,
            "horiz",
            location=_gps_at(lat=45.0, lon=-75.0, altitude=100.0),
            dt=_dt.datetime(2024, 6, 1, 22, 0, 0, tzinfo=_dt.timezone.utc),
        )
        assert result is not None
        assert result.up_label == "Zenith"
        assert result.is_fallback is False
        # Rotation should be a finite number for a real horiz computation.
        assert isinstance(result.rot_deg, float)

    def test_unknown_mode_defaults_to_ncp_without_fallback(self):
        result = get_chart_rotation_angle(10.0, 20.0, "nonsense-mode")
        assert result == ChartOrientation(0.0, "NCP", False)
