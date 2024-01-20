#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs a lightweight
server to accept socket connections
and report telescope position
Protocol based on Meade LX200
"""
import socket
from math import modf
import logging
import re
from multiprocessing import Queue
from typing import Tuple
from PiFinder.calc_utils import ra_to_deg, dec_to_deg, sf_utils
from PiFinder.catalogs import CompositeObject
from skyfield.positionlib import position_of_radec
from skyfield.api import load

sr_result = None
sequence = 0
ui_queue: Queue = None

# shortcut for skyfield timescale
ts = sf_utils.ts


def get_telescope_ra(shared_state, _):
    """
    Extract RA from current solution
    format for LX200 protocol
    RA = HH:MM:SS
    """
    solution = shared_state.solution()
    if not solution:
        return "00:00:01"

    # Convert from J2000 to now epoch
    RA_deg = solution["RA"]
    Dec_deg = solution["Dec"]
    _p = position_of_radec(ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=ts.J2000)

    RA_h, Dec, _dist = _p.radec(epoch=ts.now())

    hh, mm, ss = RA_h.hms()
    ra_result = f"{hh:02.0f}:{mm:02.0f}:{ss:02.0f}"
    logging.debug("get_telescope_ra: RA result: %s", ra_result)
    return ra_result


def get_telescope_dec(shared_state, _):
    """
    Extract DEC from current solution
    format for LX200 protocol
    DEC = +/- DD*MM'SS
    """
    solution = shared_state.solution()
    if not solution:
        return "+00*00'01"

    dec = solution["Dec"]

    # Convert from J2000 to now epoch
    RA_deg = solution["RA"]
    Dec_deg = solution["Dec"]
    _p = position_of_radec(ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=ts.J2000)

    RA_h, Dec, _dist = _p.radec(epoch=ts.now())

    dec = Dec.degrees

    mm, hh = modf(dec)
    fractional_mm, mm = modf(mm * 60.0)
    ss = round(fractional_mm * 60.0)

    if dec < 0:
        dec = abs(dec)
        sign = "-"
    else:
        sign = "+"
    dec_result = f"{sign}{hh:02.0f}*{mm:02.0f}'{ss:02.0f}"
    logging.debug("get_telescope_dec: Dec result: %s", dec_result)
    return dec_result


def respond_none(shared_state, input_str):
    return None


def respond_zero(shared_state, input_str):
    return "0"


def respond_one(shared_state, input_str):
    return "1"


def not_implemented(shared_state, input_str):
    # return "not implemented"
    return respond_none(shared_state, input_str)


def _match_to_hms(pattern: str, input_str: str) -> Tuple[int, int, int]:
    match = re.match(pattern, input_str)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return hours, minutes, seconds
    else:
        return None


def parse_sr_command(_, input_str: str):
    global sr_result
    pattern = r":Sr([-+]?\d{2}):(\d{2}):(\d{2})#"
    match = _match_to_hms(pattern, input_str)
    # logging.debug(f"Parsing sr command, match: {match}")
    if match:
        sr_result = match
        return "1"
    else:
        return "0"


def parse_sd_command(shared_state, input_str: str):
    global sr_result
    pattern = r":Sd([-+]?\d{2})\*(\d{2}):(\d{2})#"
    match = _match_to_hms(pattern, input_str)
    # logging.debug(f"Parsing sd command, match: {match}, sr_result: {sr_result}")
    if match and sr_result:
        return handle_goto_command(shared_state, sr_result, match)
    else:
        return "0"


def handle_goto_command(shared_state, ra_parsed, dec_parsed):
    global sequence, ui_queue
    ra = ra_to_deg(*ra_parsed)
    dec = dec_to_deg(*dec_parsed)
    logging.debug("handle_goto_command: ra,dec in deg, JNOW: %s, %s", ra, dec)
    _p = position_of_radec(ra_hours=ra / 15, dec_degrees=dec, epoch=ts.now())
    ra_h, dec_d, _dist = _p.radec(epoch=ts.J2000)
    sequence += 1
    comp_ra = float(ra_h._degrees)
    comp_dec = float(dec_d.degrees)
    logging.debug("Goto ra,dec in deg, J2000: %s, %s", comp_ra, comp_dec)
    constellation = sf_utils.radec_to_constellation(comp_ra, comp_dec)
    obj = CompositeObject.from_dict(
        {
            "id": -1,
            "obj_type": "",
            "ra": comp_ra,
            "dec": comp_dec,
            "const": constellation,
            "size": "",
            "mag": "",
            "catalog_code": "PUSH",
            "sequence": sequence,
            "description": f"Skysafari object nr {sequence}",
        }
    )
    logging.debug("handle_goto_command: Pushing object: %s", obj)
    shared_state.ui_state().push_object(obj)
    ui_queue.put("push_object")
    return "1"


def init_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# Function to extract command
def extract_command(s):
    match = re.search(r":([A-Za-z]+)", s)
    return match.group(1) if match else None


def run_server(shared_state, p_ui_queue):
    global ui_queue
    try:
        init_logging()
        ui_queue = p_ui_queue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            logging.info("Starting SkySafari server")
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("", 4030))
            server_socket.listen(1)
            out_data = None
            while True:
                client_socket, address = server_socket.accept()
                while True:
                    in_data = client_socket.recv(1024).decode()
                    if in_data:
                        logging.debug("Received from skysafari: '%s'", in_data)
                        command = extract_command(in_data)
                        if command:
                            command_handler = lx_command_dict.get(command, None)
                            if command_handler:
                                out_data = command_handler(shared_state, in_data)
                            else:
                                logging.warn("Unknown Command: %s", in_data)
                                out_data = not_implemented(shared_state, in_data)
                    else:
                        break

                    if out_data:
                        if out_data in ("0", "1"):
                            client_socket.send(bytes(out_data, "utf-8"))
                        else:
                            client_socket.send(bytes(out_data + "#", "utf-8"))
                        out_data = None
                client_socket.close()
    except Exception as e:
        print(e)
        print("exited skysafari")
        logging.exception("An error occurred in the skysafari server")


lx_command_dict = {
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "RS": respond_none,
    "MS": respond_zero,
    "Sd": parse_sd_command,
    "Sr": parse_sr_command,
    "Q": respond_none,
}
