#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs a lightweight
server to accept socket connections
and report telescope position
Protocol based on Meade LX200

This is used by SkySafari (iOS, iPadOS) and Stellarium.  Both read the
telescope's position; both can also push a target back to the PiFinder's
observing list.
"""

import socket
import logging
import re
from multiprocessing import Queue
from typing import List, Optional, Tuple, Union
from PiFinder.calc_utils import ra_to_deg, dec_to_deg, dec_to_dms_exact, sf_utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.multiproclogging import MultiprocLogging
from skyfield.positionlib import position_of_radec
import sys
import time

logger = logging.getLogger("PosServer")

sr_result = None
sequence = 0
ui_queue: Queue

# Set when a client sends the LX200 ACK byte on connect.  Stellarium does;
# SkySafari never has, which is why this doubles as "the client is Stellarium".
# It selects the input epoch, the :D# reply and the :Q# reply, so a client that
# tripped it by accident would misbehave in several ways at once.
is_stellarium = False

# Stellarium will not push a target while it believes the scope's site differs
# from its own, so it sets the site with :St#/:Sg# and expects to read the same
# values back.  PiFinder takes its real site from GPS and ignores these for
# positioning -- they are stored only to echo.  Cleared per connection.
stellarium_latitude = ""
stellarium_longitude = ""

# shortcut for skyfield timescale
ts = sf_utils.ts


def get_telescope_ra(shared_state, _):
    """
    Extract RA from current solution
    format for LX200 protocol
    RA = HH:MM:SS
    """
    solution = shared_state.solution()
    dt = shared_state.datetime()
    if not solution or not dt or not solution.has_pointing():
        return "+00*00'01"

    aligned = solution.pointing.aligned.estimate
    # Convert from J2000 to now epoch
    try:
        RA_deg = float(aligned.RA)
        Dec_deg = float(aligned.Dec)
    except TypeError:
        hh = 0
        mm = 0
        ss = 0
        ra_result = f"{hh:02.0f}:{mm:02.0f}:{ss:02.0f}"
        logger.warning("get_telescope_ra: Type Error")
        return ra_result

    _p = position_of_radec(ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=ts.J2000)

    RA_h, _Dec, _dist = _p.radec(epoch=ts.from_datetime(dt))

    hh, mm, ss = RA_h.hms()
    ra_result = f"{hh:02.0f}:{mm:02.0f}:{ss:02.0f}"
    logger.debug("get_telescope_ra: RA result: %s", ra_result)
    return ra_result


def get_telescope_dec(shared_state, _):
    """
    Extract DEC from current solution
    format for LX200 protocol
    DEC = +/- DD*MM'SS
    """
    solution = shared_state.solution()
    dt = shared_state.datetime()
    if not solution or not dt or not solution.has_pointing():
        return "+00*00'01"

    aligned = solution.pointing.aligned.estimate
    # Convert from J2000 to now epoch
    try:
        RA_deg = float(aligned.RA)
        Dec_deg = float(aligned.Dec)
    except TypeError:
        sign = "+"
        hh = 0
        mm = 0
        ss = 0
        dec_result = f"{sign}{hh:02.0f}*{mm:02.0f}'{ss:02.0f}"
        logger.warning("get_telescope_dec: Type error in coords")
        return dec_result

    _p = position_of_radec(ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=ts.J2000)

    _RA_h, Dec, _dist = _p.radec(epoch=ts.from_datetime(dt))

    sign, d, m, s = dec_to_dms_exact(Dec.degrees)
    dec_result = f"{sign}{d:02d}*{m:02d}'{round(s):02d}"
    logger.debug("get_telescope_dec: Dec result: %s", dec_result)
    return dec_result


def get_distance_bars(_shared_state, _input_str) -> str:
    """:D# -- one 0x7f byte per "bar" of slew left; empty means slew complete."""
    # Stellarium will not send goto data to a scope it believes is still
    # slewing, so report the slew complete.  PiFinder never slews at all, so
    # this is the honest answer either way; SkySafari keeps the single bar it
    # has always been sent.
    if is_stellarium:
        return ""
    return "\x7f"


def get_firmware_date(_shared_state, _input_str):
    return "Jan 28 2026"


def get_firmware_version(_shared_state, _input_str):
    return "01.0"


def get_product(_shared_state, _input_str):
    return "PiFinder"


def get_firmware_time(_shared_state, _input_str):
    return "17:25:00"


def get_status(_shared_state, _input_str):
    # Indicates alt-az mode, tracking, and 1-star aligned
    return "AT1"


def respond_none(shared_state, input_str):
    return None


def respond_zero(shared_state, input_str):
    return "0"


def respond_one(shared_state, input_str):
    return "1"


def not_implemented(shared_state, input_str):
    # return "not implemented"
    return respond_none(shared_state, input_str)


def abort_slew(_shared_state, _input_str) -> Optional[str]:
    """:Q# -- Abort slew.  LX200 specifies no reply.

    Stellarium will not go on to send a target until it sees a reply here, but
    an unsolicited byte can desync SkySafari's response parser, so answer only
    the client that identified itself with an ACK.
    """
    return "1" if is_stellarium else None


def _match_to_hms(pattern: str, input_str: str) -> Union[Tuple[int, int, int], None]:
    match = re.search(pattern, input_str)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return hours, minutes, seconds
    else:
        return None


# Stellarium prefixes every command with '#'; SkySafari does not.  One pattern
# with an optional prefix accepts both, so neither parser needs to know which
# client it is talking to.
_SR_PATTERN = r"#?:Sr([-+]?\d{2}):(\d{2}):(\d{2})#"

# Standard LX200 declination separates degrees from minutes with '*'.
# Stellarium has been observed sending ':' instead, so accept either.
_SD_PATTERN = r"#?:Sd([-+]?\d{2})[*:](\d{2}):(\d{2})#"


def parse_sr_command(_shared_state, input_str: str) -> str:
    global sr_result
    match = _match_to_hms(_SR_PATTERN, input_str)
    logger.debug("Parsing sr command, match: %s", match)
    if match:
        sr_result = match
        return "1"
    else:
        return "0"


def parse_sd_command(shared_state, input_str: str) -> str:
    global sr_result
    match = _match_to_hms(_SD_PATTERN, input_str)
    logger.debug("Parsing sd command, match: %s, sr_result: %s", match, sr_result)
    if match and sr_result:
        return handle_goto_command(shared_state, sr_result, match)
    else:
        return "0"


def handle_goto_command(shared_state, ra_parsed, dec_parsed):
    global sequence, ui_queue, is_stellarium
    ra = ra_to_deg(*ra_parsed)
    dec = dec_to_deg(*dec_parsed)
    if is_stellarium:
        comp_ra, comp_dec = ra, dec
    else:
        logger.debug("handle_goto_command: ra,dec in deg, JNOW: %s, %s", ra, dec)
        _p = position_of_radec(ra_hours=ra / 15, dec_degrees=dec, epoch=ts.now())
        ra_h, dec_d, _ = _p.radec(epoch=ts.J2000)
        comp_ra = float(ra_h._degrees)
        comp_dec = float(dec_d.degrees)
    sequence += 1
    logger.debug("Goto ra,dec in deg, J2000: %s, %s", comp_ra, comp_dec)
    constellation = sf_utils.radec_to_constellation(comp_ra, comp_dec)
    obj = CompositeObject.from_dict(
        {
            "id": -1,
            "object_id": sys.maxsize - sequence,
            "obj_type": "",
            "ra": comp_ra,
            "dec": comp_dec,
            "const": constellation,
            "size": SizeObject([]),
            "mag": MagnitudeObject([]),
            "catalog_code": "PUSH",
            "sequence": sequence,
            # Either planetarium app can push, so don't name one of them here.
            "description": f"Pushed object nr {sequence}",
        }
    )
    logger.debug("handle_goto_command: Pushing object: %s", obj)
    shared_state.ui_state().add_recent(obj)
    shared_state.ui_state().set_new_pushto(True)
    ui_queue.put("push_object")
    return "1"


# Site and clock commands.  Stellarium runs through these during its connection
# handshake and gives up on the push if they go unanswered.


def set_current_date(_shared_state, _input_str) -> str:
    """:SCMM/DD/YY# -- accept and discard the client's date.

    PiFinder takes its civil time from GPS or manual entry, so the value is
    dropped.  The reply shape is fixed by the protocol: "1" followed by the
    already-terminated status string a Meade mount sends while it rebuilds
    planetary data.
    """
    return "1Updating Planetary Data#                         #"


def get_current_date(shared_state, _input_str) -> Optional[str]:
    """:GC# -- local calendar date as MM/DD/YY.

    Hardcoded rather than %x: LX200 fixes this format, while %x follows the
    process locale, which the i18n work can change out from under us.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    return dt.strftime("%m/%d/%y")


def get_current_time(shared_state, _input_str) -> Optional[str]:
    """:GL# -- local civil time as 24-hour HH:MM:SS.

    LX200 defines this as *local* time, so read the observer's zone directly
    (ADR-0018) rather than offsetting UTC by hand.  %X is avoided for the same
    locale reason as %x above.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    return dt.strftime("%H:%M:%S")


def get_utc_offset(shared_state, _input_str) -> Optional[str]:
    """:GG# -- hours to ADD to local time to reach UTC, as sHH (or sHH.H).

    Note the inverted sign: LX200 asks for the correction *towards* UTC, so US
    Eastern (UTC-5) answers "+05" and Berlin in winter (UTC+1) answers "-01".
    Half-hour zones use the sHH.H form; zones on a quarter hour round to the
    nearest tenth, which is as fine as the protocol goes.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    offset = dt.utcoffset()
    if offset is None:
        return None
    hours = -offset.total_seconds() / 3600.0
    sign = "-" if hours < 0 else "+"
    magnitude = abs(hours)
    if magnitude == int(magnitude):
        return f"{sign}{int(magnitude):02d}"
    return f"{sign}{magnitude:04.1f}"


# The site setters keep the sign and the degree width the client used so :Gt#
# and :Gg# can echo it back unchanged; only the seconds field, which the
# getters have no room for, is dropped.
_SITE_LAT_PATTERN = r"#?:St([-+]?)(\d{1,2})\*(\d{2})"
_SITE_LON_PATTERN = r"#?:Sg([-+]?)(\d{1,3})\*(\d{2})"


def set_latitude(_shared_state, input_str: str) -> str:
    """:StsDD*MM# -- remember the client's site latitude for :Gt# to echo."""
    global stellarium_latitude
    match = re.search(_SITE_LAT_PATTERN, input_str)
    if not match:
        logger.debug("set_latitude: no match in %s", input_str)
        return "0"
    sign, degrees, minutes = match.groups()
    stellarium_latitude = f"{sign or '+'}{int(degrees):02d}*{minutes}"
    return "1"


def set_longitude(_shared_state, input_str: str) -> str:
    """:SgDDD*MM# -- remember the client's site longitude for :Gg# to echo."""
    global stellarium_longitude
    match = re.search(_SITE_LON_PATTERN, input_str)
    if not match:
        logger.debug("set_longitude: no match in %s", input_str)
        return "0"
    sign, degrees, minutes = match.groups()
    stellarium_longitude = f"{sign}{int(degrees):03d}*{minutes}"
    return "1"


def _deg_to_dm(value: float, degree_len: int) -> str:
    """Format signed decimal degrees as the LX200 sDD*MM form.

    Rounds to whole arcminutes and carries into the degrees field, so 42.999
    formats as "+43*00" rather than the out-of-range "+42*60".
    """
    sign = "-" if value < 0 else "+"
    degrees, minutes = divmod(round(abs(value) * 60), 60)
    return f"{sign}{degrees:0{degree_len}d}*{minutes:02d}"


def _lon_to_meade_dm(value: float) -> str:
    """Format signed east-positive longitude as Meade's unsigned DDD*MM.

    Meade counts site longitude positive *westward* across 000-359 -- the same
    convention :Sg# accepts -- while PiFinder stores it signed and
    east-positive.  Negating and wrapping converts between the two: Boston
    (-71.06) becomes 071*04 and Berlin (+13.4) becomes 346*36.  The wrap is
    applied after rounding to minutes so a site just east of Greenwich cannot
    round up into a nonexistent 360*00.
    """
    degrees, minutes = divmod(round(-value * 60) % (360 * 60), 60)
    return f"{degrees:03d}*{minutes:02d}"


def get_latitude(shared_state, _input_str) -> str:
    """:Gt# -- current site latitude as sDD*MM."""
    if stellarium_latitude:
        return stellarium_latitude
    return _deg_to_dm(shared_state.location().lat, 2)


def get_longitude(shared_state, _input_str) -> str:
    """:Gg# -- current site longitude as DDD*MM."""
    if stellarium_longitude:
        return stellarium_longitude
    return _lon_to_meade_dm(shared_state.location().lon)


# Function to extract command
def extract_command(s):
    match = re.search(r":([A-Za-z]+)", s)
    return match.group(1) if match else None


lx_command_dict = {
    "D": get_distance_bars,
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "GVD": get_firmware_date,
    "GVN": get_firmware_version,
    "GVP": get_product,
    "GVT": get_firmware_time,
    "GW": get_status,
    "RS": respond_none,  # Set slew rate to max
    "MS": respond_zero,  # Slew to object
    "Q": abort_slew,  # Abort
    "U": respond_none,  # Precision toggle
    "Sd": parse_sd_command,  # Set declination
    "Sr": parse_sr_command,  # Set RA
    # Site and clock, needed for Stellarium to get as far as pushing a target.
    # PiFinder takes its own time from GPS or manual entry and will not be
    # steered by the client's clock, so :SG# (UTC offset) and :SL# (local time)
    # are acknowledged and discarded -- Stellarium abandons the handshake if
    # they are refused.
    "SG": respond_one,  # Set UTC offset
    "SL": respond_one,  # Set local time
    "SC": set_current_date,  # Set local date
    "St": set_latitude,  # Set site latitude
    "Sg": set_longitude,  # Set site longitude
    "GC": get_current_date,  # Get local date
    "GL": get_current_time,  # Get local time
    "GG": get_utc_offset,  # Get UTC offset
    "Gt": get_latitude,  # Get site latitude
    "Gg": get_longitude,  # Get site longitude
}


def setup_server_socket():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("", 4030))
    server_socket.listen(1)
    return server_socket


def split_frames(data: str) -> List[str]:
    """Split one read into individual '#'-terminated command frames.

    Stellarium batches commands and prefixes each with '#', so a single recv
    can carry "#:Sr...##:Sd...#".  Handling only the first match would drop the
    :Sd# that actually fires the goto, and the push would silently never
    happen.  A trailing fragment comes back as its own frame: the bare ACK byte
    needs that, and a command genuinely torn across two reads simply fails to
    match, exactly as it did before.
    """
    frames = []
    current = ""
    for char in data:
        current += char
        # A leading '#' is Stellarium's prefix rather than a terminator, so a
        # frame only closes once the ':' introducer has been seen.
        if char == "#" and ":" in current:
            frames.append(current)
            current = ""
    if current:
        frames.append(current)
    return frames


def handle_frame(frame: str, shared_state) -> Optional[str]:
    """Dispatch one command frame, returning the reply to send, if any."""
    global is_stellarium

    command = extract_command(frame)
    if command:
        command_handler = lx_command_dict.get(command, not_implemented)
        out_data = command_handler(shared_state, frame)
        if out_data is None:
            return None
        # "0"/"1"/"AT1" go out bare, and a couple of handlers build their own
        # terminator.  Without the endswith() check, :D# and :SC# would each
        # leave a stray extra '#' in the stream.
        if out_data in ("0", "1", "AT1") or out_data.endswith("#"):
            return out_data
        return out_data + "#"

    # Special case for the ACK command in the LX200 protocol sent by Stellarium
    # No leading : for the ACK command but Stellarium leads all commands with #
    if frame.endswith("\x06"):
        is_stellarium = True
        # "P" claims a polar mount.  PiFinder is alt-az and :GW# still says so,
        # but Stellarium will not push a target to a scope that answers "A"
        # here.  Only a client that sent an ACK ever reads this byte, and so
        # far only Stellarium sends one, so SkySafari never sees it.
        return "P"

    return None


def handle_client(client_socket, shared_state):
    global is_stellarium, stellarium_latitude, stellarium_longitude
    client_socket.settimeout(60)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Everything the last client taught us dies with its connection, so a
    # SkySafari session following a Stellarium one inherits neither the flag
    # nor the echoed site.
    is_stellarium = False
    stellarium_latitude = ""
    stellarium_longitude = ""

    while True:
        try:
            in_data = client_socket.recv(1024).decode()
            if not in_data:
                break

            logging.debug("Received from client: %s", in_data)
            for frame in split_frames(in_data):
                response = handle_frame(frame, shared_state)
                if response is not None:
                    client_socket.send(response.encode())
        except socket.timeout:
            logging.warning("Connection timed out.")
            break
        except ConnectionResetError:
            logging.warning("Client disconnected unexpectedly.")
            break

    client_socket.close()


def run_server(shared_state, p_ui_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    global ui_queue
    ui_queue = p_ui_queue
    logger = logging.getLogger(__name__)

    while True:
        try:
            with setup_server_socket() as server_socket:
                logger.info("SkySafari server started and listening")
                while True:
                    client_socket, address = server_socket.accept()
                    logger.debug("New connection from %s", address)
                    handle_client(client_socket, shared_state)
        except Exception:
            logger.exception("Unexpected server error")
            logger.info("Attempting to restart server in 5 seconds...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Server shutting down...")
            break
