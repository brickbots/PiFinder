"""Unit tests for the LX200 position server.

`pos_server` talks to SkySafari and Stellarium over the same socket, and the two
clients disagree about framing, epoch and which commands must be answered.
Nearly all of that lives in pure functions, so it can be exercised without a
socket.  These tests pin the arithmetic and the parsing, and guard the handful
of places where a Stellarium accommodation could leak into a SkySafari session.
"""

import datetime
from unittest.mock import MagicMock

import pytest
import pytz

from PiFinder import pos_server


@pytest.fixture(autouse=True)
def reset_module_state():
    """Clear the module globals a connection would reset, before and after."""
    pos_server.is_stellarium = False
    pos_server.stellarium_latitude = ""
    pos_server.stellarium_longitude = ""
    pos_server.sr_result = None
    yield
    pos_server.is_stellarium = False
    pos_server.stellarium_latitude = ""
    pos_server.stellarium_longitude = ""
    pos_server.sr_result = None


def make_shared_state(lat=42.36, lon=-71.06, tz="America/New_York", when=None):
    """A shared_state stub with just the accessors pos_server reads."""
    shared_state = MagicMock()
    shared_state.location.return_value = MagicMock(lat=lat, lon=lon, timezone=tz)
    if when is None:
        shared_state.local_datetime.return_value = None
    else:
        shared_state.local_datetime.return_value = when.astimezone(pytz.timezone(tz))
    return shared_state


# --------------------------------------------------------------------------
# Degrees to degrees/arcminutes
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        # The cases the string-surgery implementation got wrong: any fractional
        # part below 0.17 degrees came out ten times too small, and a fraction
        # that scaled past 59 produced an out-of-range "*60".
        (42.36, "+42*22"),
        (42.10, "+42*06"),
        (42.05, "+42*03"),
        (-71.06, "-71*04"),
        (42.00, "+42*00"),
        # Rounding must carry into the degrees field rather than emit "*60".
        (42.999, "+43*00"),
        (0.0, "+00*00"),
        (-0.004, "-00*00"),
        (89.5, "+89*30"),
        (-89.99, "-89*59"),  # 89 deg 59.4 min rounds down, not up to *60
        (-89.999, "-90*00"),  # ...but 89 deg 59.94 min does carry
    ],
)
def test_deg_to_dm_latitude(value, expected):
    assert pos_server._deg_to_dm(value, 2) == expected


@pytest.mark.unit
def test_deg_to_dm_pads_to_requested_width():
    assert pos_server._deg_to_dm(7.5, 2) == "+07*30"
    assert pos_server._deg_to_dm(7.5, 3) == "+007*30"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        # Meade counts site longitude positive westward over 000-359, so a
        # western site loses its sign and an eastern one wraps.
        (-71.06, "071*04"),
        (13.4, "346*36"),
        (0.0, "000*00"),
        (-179.99, "179*59"),
        (179.99, "180*01"),
        # Just east of Greenwich must not round up into a nonexistent 360*00.
        (0.001, "000*00"),
    ],
)
def test_lon_to_meade_dm(value, expected):
    result = pos_server._lon_to_meade_dm(value)
    assert result == expected
    assert 0 <= int(result.split("*")[0]) < 360


# --------------------------------------------------------------------------
# Sr / Sd parsing
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "frame",
    [
        ":Sr05:34:32#",  # SkySafari
        "#:Sr05:34:32#",  # Stellarium prefixes with '#'
    ],
)
def test_parse_sr_accepts_both_framings(frame):
    assert pos_server.parse_sr_command(None, frame) == "1"
    assert pos_server.sr_result == (5, 34, 32)


@pytest.mark.unit
def test_parse_sr_rejects_malformed():
    assert pos_server.parse_sr_command(None, ":Sr5:34:32#") == "0"
    assert pos_server.sr_result is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "frame",
    [
        ":Sd+22*00:52#",  # standard LX200 uses '*'
        "#:Sd+22*00:52#",  # Stellarium's prefix, standard separator
        "#:Sd+22:00:52#",  # Stellarium has been seen sending ':'
    ],
)
def test_parse_sd_accepts_both_framings_and_separators(frame, monkeypatch):
    captured = {}

    def fake_goto(shared_state, ra_parsed, dec_parsed):
        captured["ra"] = ra_parsed
        captured["dec"] = dec_parsed
        return "1"

    monkeypatch.setattr(pos_server, "handle_goto_command", fake_goto)
    pos_server.parse_sr_command(None, ":Sr05:34:32#")

    assert pos_server.parse_sd_command(None, frame) == "1"
    assert captured["ra"] == (5, 34, 32)
    assert captured["dec"] == (22, 0, 52)


@pytest.mark.unit
def test_parse_sd_without_prior_sr_does_not_push(monkeypatch):
    monkeypatch.setattr(
        pos_server,
        "handle_goto_command",
        lambda *a: pytest.fail("goto fired without an RA"),
    )
    assert pos_server.parse_sd_command(None, ":Sd+22*00:52#") == "0"


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "data, expected",
    [
        (":GR#", [":GR#"]),
        # A coalesced Sr+Sd pair must yield both frames; keeping only the
        # first would drop the Sd that actually fires the goto.
        (":Sr05:34:32#:Sd+22*00:52#", [":Sr05:34:32#", ":Sd+22*00:52#"]),
        (
            "#:Sr05:34:32##:Sd+22*00:52#",
            ["#:Sr05:34:32#", "#:Sd+22*00:52#"],
        ),
        # The ACK byte has no terminator and must still come through.
        ("\x06", ["\x06"]),
        ("#\x06", ["#\x06"]),
        # A bare prefix arriving alone is harmless; the next read carries the
        # command, which the optional '#' in the patterns still matches.
        ("#", ["#"]),
        ("", []),
    ],
)
def test_split_frames(data, expected):
    assert pos_server.split_frames(data) == expected


@pytest.mark.unit
def test_coalesced_sr_sd_reaches_the_goto(monkeypatch):
    """End-to-end on the framing bug: one read carrying both must push once."""
    pushed = []
    monkeypatch.setattr(
        pos_server,
        "handle_goto_command",
        lambda shared_state, ra, dec: pushed.append((ra, dec)) or "1",
    )
    pos_server.is_stellarium = True

    replies = [
        pos_server.handle_frame(frame, None)
        for frame in pos_server.split_frames("#:Sr05:34:32##:Sd+22*00:52#")
    ]

    assert replies == ["1", "1"]
    assert pushed == [((5, 34, 32), (22, 0, 52))]


# --------------------------------------------------------------------------
# Response terminators
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_distance_bars_terminator_is_not_doubled():
    """:D# with no bars is a bare terminator, not '##'."""
    pos_server.is_stellarium = True
    assert pos_server.handle_frame(":D#", None) == "#"

    pos_server.is_stellarium = False
    assert pos_server.handle_frame(":D#", None) == "\x7f#"


@pytest.mark.unit
def test_set_current_date_reply_is_not_re_terminated():
    reply = pos_server.handle_frame(":SC03/15/26#", make_shared_state())
    assert reply == "1Updating Planetary Data#                         #"
    assert not reply.endswith("##")


@pytest.mark.unit
def test_plain_payloads_still_get_a_terminator():
    assert pos_server.handle_frame(":GVP#", None) == "PiFinder#"
    assert pos_server.handle_frame(":GW#", None) == "AT1"


# --------------------------------------------------------------------------
# SkySafari must not inherit Stellarium's accommodations
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_abort_is_silent_for_skysafari():
    """LX200 specifies no reply to :Q#; an extra byte desyncs SkySafari."""
    pos_server.is_stellarium = False
    assert pos_server.handle_frame(":Q#", None) is None


@pytest.mark.unit
def test_abort_answers_stellarium():
    pos_server.is_stellarium = True
    assert pos_server.handle_frame(":Q#", None) == "1"


@pytest.mark.unit
def test_ack_identifies_stellarium_and_reports_polar():
    assert pos_server.handle_frame("\x06", None) == "P"
    assert pos_server.is_stellarium is True


@pytest.mark.unit
def test_status_stays_alt_az():
    """:GW# is the reply SkySafari reads, and PiFinder really is alt-az."""
    pos_server.is_stellarium = True
    assert pos_server.get_status(None, None) == "AT1"


@pytest.mark.unit
def test_handle_client_resets_stellarium_state_between_connections():
    """A SkySafari session after a Stellarium one starts clean."""
    pos_server.is_stellarium = True
    pos_server.stellarium_latitude = "+42*21"
    pos_server.stellarium_longitude = "071*04"

    client = MagicMock()
    client.recv.return_value = b""

    pos_server.handle_client(client, make_shared_state())

    assert pos_server.is_stellarium is False
    assert pos_server.stellarium_latitude == ""
    assert pos_server.stellarium_longitude == ""


# --------------------------------------------------------------------------
# Site echo
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_site_latitude_round_trips_what_the_client_set():
    assert pos_server.set_latitude(None, "#:St+42*21#") == "1"
    assert pos_server.get_latitude(make_shared_state(), None) == "+42*21"


@pytest.mark.unit
def test_site_latitude_survives_the_seconds_form():
    """The old input_str[4:10] slice silently truncated this to '+42*21'."""
    assert pos_server.set_latitude(None, "#:St+42*21:36#") == "1"
    assert pos_server.get_latitude(make_shared_state(), None) == "+42*21"


@pytest.mark.unit
def test_site_latitude_keeps_the_sign_without_the_prefix():
    """':St+42*21#' unprefixed used to lose its sign to the slice."""
    assert pos_server.set_latitude(None, ":St-42*21#") == "1"
    assert pos_server.get_latitude(make_shared_state(), None) == "-42*21"


@pytest.mark.unit
def test_site_longitude_round_trips_what_the_client_set():
    assert pos_server.set_longitude(None, "#:Sg071*04#") == "1"
    assert pos_server.get_longitude(make_shared_state(), None) == "071*04"


@pytest.mark.unit
def test_site_setters_reject_garbage():
    assert pos_server.set_latitude(None, "#:Stnonsense#") == "0"
    assert pos_server.stellarium_latitude == ""
    assert pos_server.set_longitude(None, "#:Sgnonsense#") == "0"
    assert pos_server.stellarium_longitude == ""


@pytest.mark.unit
def test_site_falls_back_to_the_gps_fix():
    shared_state = make_shared_state(lat=42.36, lon=-71.06)
    assert pos_server.get_latitude(shared_state, None) == "+42*22"
    assert pos_server.get_longitude(shared_state, None) == "071*04"


# --------------------------------------------------------------------------
# Date, time and UTC offset
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_date_and_time_are_local_and_locale_independent():
    """22:30 UTC on 15 March is still the 15th, 18:30, in New York."""
    when = datetime.datetime(2026, 3, 15, 22, 30, 15, tzinfo=pytz.utc)
    shared_state = make_shared_state(tz="America/New_York", when=when)

    assert pos_server.get_current_date(shared_state, None) == "03/15/26"
    assert pos_server.get_current_time(shared_state, None) == "18:30:15"


@pytest.mark.unit
def test_local_date_can_differ_from_the_utc_date():
    """01:30 UTC on the 16th is still the evening of the 15th in New York."""
    when = datetime.datetime(2026, 3, 16, 1, 30, 0, tzinfo=pytz.utc)
    shared_state = make_shared_state(tz="America/New_York", when=when)

    assert pos_server.get_current_date(shared_state, None) == "03/15/26"
    assert pos_server.get_current_time(shared_state, None) == "21:30:00"


@pytest.mark.unit
@pytest.mark.parametrize(
    "tz, expected",
    [
        # LX200 wants the hours to ADD to local time to reach UTC, so the sign
        # is inverted relative to the zone's own offset.
        ("America/New_York", "+04"),  # UTC-4 in June
        ("Europe/Berlin", "-02"),  # UTC+2 in June
        ("UTC", "+00"),
        ("Asia/Kolkata", "-05.5"),  # UTC+5:30 uses the sHH.H form
    ],
)
def test_utc_offset_sign_and_shape(tz, expected):
    when = datetime.datetime(2026, 6, 21, 12, 0, 0, tzinfo=pytz.utc)
    shared_state = make_shared_state(tz=tz, when=when)
    assert pos_server.get_utc_offset(shared_state, None) == expected


@pytest.mark.unit
def test_clock_commands_are_silent_before_a_time_fix():
    """No GPS lock yet: answer nothing rather than crash the server process."""
    shared_state = make_shared_state(when=None)
    assert pos_server.get_current_date(shared_state, None) is None
    assert pos_server.get_current_time(shared_state, None) is None
    assert pos_server.get_utc_offset(shared_state, None) is None
    assert pos_server.handle_frame(":GL#", shared_state) is None
