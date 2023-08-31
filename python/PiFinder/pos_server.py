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
from typing import Tuple, List
from PiFinder.calc_utils import ra_to_deg, dec_to_deg
from PiFinder.catalogs import CompositeObject


sr_result = None
sequence = 0


def get_telescope_ra(shared_state, _):
    """
    Extract RA from current solution
    format for LX200 protocol
    RA = HH:MM:SS
    """
    solution = shared_state.solution()
    if not solution:
        return "00:00:01"

    ra = solution["RA"]
    if ra < 0.0:
        ra = ra + 360
    mm, hh = modf(ra / 15.0)
    _, mm = modf(mm * 60.0)
    ss = round(_ * 60.0)
    return f"{hh:02.0f}:{mm:02.0f}:{ss:02.0f}"


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
    if dec < 0:
        dec = abs(dec)
        sign = "-"
    else:
        sign = "+"

    mm, hh = modf(dec)
    fractional_mm, mm = modf(mm * 60.0)
    ss = round(fractional_mm * 60.0)
    return f"{sign}{hh:02.0f}*{mm:02.0f}'{ss:02.0f}"


def respond_none(shared_state, input_str):
    return None


def respond_zero(shared_state, input_str):
    return "0"


def respond_one(shared_state, input_str):
    return "1"


def not_implemented(shared_state, input_str):
    return "not implemented"


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
    if match:
        sr_result = match
        return "1"
    else:
        return "0"


def parse_sd_command(shared_state, input_str: str):
    global sr_result
    pattern = r":Sd([-+]?\d{2})\*(\d{2}):(\d{2})#"
    match = _match_to_hms(pattern, input_str)
    if match and sr_result:
        return handle_goto_command(shared_state, sr_result, match)
    else:
        return "0"


def handle_goto_command(shared_state, ra_parsed, dec_parsed):
    global sequence
    ra = ra_to_deg(*ra_parsed)
    dec = dec_to_deg(*dec_parsed)
    logging.debug(f"goto {ra_parsed} {dec_parsed}")
    sequence += 1
    obj = CompositeObject(
        {
            "id": -1,
            "obj_type": "",
            "ra": ra,
            "dec": dec,
            "const": "",
            "size": "",
            "mag": "",
            "catalog_code": "PUSH",
            "sequence": sequence,
            "description": f"Skysafari object nr {sequence}",
        }
    )
    print(f"shared state: {shared_state}")
    shared_state.ui_state().set_target_and_add_to_history(obj)
    return "1"


def parse_command(input_str: str) -> List:
    command = input_str[1:3]
    logging.debug(f"command: '{command}'")
    command_handler = lx_command_dict.get(command)
    if command_handler:
        return command_handler()
    else:
        logging.debug(f"Unknown Command: '{input_str}'")
        return "0"


def run_server(shared_state, _):
    try:
        print("Starting skysafari")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            logging.info("starting skysafari server")
            server_socket.bind(("", 4030))
            server_socket.listen(1)
            out_data = None
            while True:
                client_socket, address = server_socket.accept()
                while True:
                    in_data = client_socket.recv(1024).decode()
                    if in_data:
                        print(f"Received from skysafari: ''{in_data}''")
                        logging.debug(f"Received from skysafari: '{in_data}'")
                        if in_data.startswith(":"):
                            command = in_data[1:3]
                            command_handler = lx_command_dict.get(command, None)
                            if command_handler:
                                out_data = command_handler(shared_state, in_data)
                            else:
                                print("Unknown Command:", in_data)
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


lx_command_dict = {
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "RS": respond_none,
    "MS": respond_zero,
    "Sd": parse_sd_command,
    "Sr": parse_sr_command,
}
