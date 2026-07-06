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
def test_svinfo_only_code_locked_counted_as_seen(parser):
    # Idle channels (e.g. SBAS) and cold-start acquisition candidates
    # (quality < 4 with an estimated cno) must not inflate the seen count.
    payload = make_svinfo_payload(
        [
            (0, 14, 0x0D, 4, 26, 30, 90),
            (7, 25, 0x00, 2, 9, 0, 0),
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


def make_nav_sat_block(gnss_id, sv_id, cno, elev, azim, flags):
    return struct.pack("<BBBbhhI", gnss_id, sv_id, cno, elev, azim, 0, flags)


def make_nav_sat_payload(svs):
    header = struct.pack("<IBBH", 1000, 1, len(svs), 0)
    return header + b"".join(make_nav_sat_block(*sv) for sv in svs)


@pytest.mark.unit
def test_nav_sat_used_from_svused_bit(parser):
    # flags bits 0-2 = quality indicator, bit 3 = svUsed
    payload = make_nav_sat_payload(
        [
            (0, 17, 27, 45, 180, 0x0C),  # quality 4, used
            (0, 13, 15, -5, 300, 0x04),  # quality 4, tracked but not used
            (0, 25, 9, 0, 0, 0x02),  # acquisition candidate: not seen
            (6, 3, 0, 0, 0, 0x01),  # searching, no signal: not seen
        ]
    )
    result = parser._parse_nav_sat(payload)

    assert result["nSat"] == 2
    sat17, sat13 = result["satellites"]
    assert (sat17["id"], sat17["used"], sat17["quality"]) == (17, True, 4)
    assert (sat13["id"], sat13["used"], sat13["elevation"]) == (13, False, -5)
