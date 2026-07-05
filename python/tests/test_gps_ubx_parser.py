import struct

import pytest

from PiFinder.gps_ubx_parser import UBXParser


def make_svinfo_channel(chn, svid, flags, quality, cno, elev, azim, prres=0):
    """Build one 12-byte UBX-NAV-SVINFO repeated block."""
    return struct.pack("<BBBBBbhi", chn, svid, flags, quality, cno, elev, azim, prres)


def make_svinfo_payload(channels):
    header = struct.pack("<IBBH", 1000, len(channels), 0, 0)
    return header + b"".join(make_svinfo_channel(*ch) for ch in channels)


@pytest.fixture
def parser():
    return UBXParser.__new__(UBXParser)


@pytest.mark.unit
def test_svinfo_field_alignment(parser):
    # chn, svid, flags (bit0 = used in fix), quality, cno, elev, azim
    payload = make_svinfo_payload(
        [
            (4, 17, 0x0D, 4, 27, 45, 180),
            (2, 13, 0x1C, 4, 15, -5, 300),
        ]
    )
    result = parser._parse_nav_svinfo(payload)

    assert result["class"] == "NAV-SVINFO"
    assert result["nSat"] == 2
    assert result["uSat"] == 1

    sat13, sat17 = result["satellites"]
    assert sat17["id"] == 17
    assert sat17["signal"] == 27
    assert sat17["elevation"] == 45
    assert sat17["azimuth"] == 180
    assert sat17["used"] is True

    assert sat13["id"] == 13
    assert sat13["signal"] == 15
    assert sat13["elevation"] == -5
    assert sat13["used"] is False


@pytest.mark.unit
def test_svinfo_idle_channels_not_counted_as_seen(parser):
    # Searching/idle channels (e.g. SBAS) report quality > 0 but cno == 0
    # and must not inflate the seen count.
    payload = make_svinfo_payload(
        [
            (0, 14, 0x0D, 4, 26, 30, 90),
            (11, 120, 0x10, 1, 0, 0, 0),
            (5, 193, 0x10, 1, 0, 0, 0),
        ]
    )
    result = parser._parse_nav_svinfo(payload)

    assert result["nSat"] == 1
    assert result["uSat"] == 1
    assert result["satellites"][0]["id"] == 14


@pytest.mark.unit
def test_svinfo_too_short(parser):
    assert "error" in parser._parse_nav_svinfo(b"\x00" * 4)
