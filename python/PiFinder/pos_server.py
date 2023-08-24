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
from typing import Tuple

def get_telescope_ra(shared_state):
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


def get_telescope_dec(shared_state):
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


def respond_none(shared_state):
    return None


def not_implemented(shared_state):
    return "not implemented"

def parse_sr_command(input_str: str):
    pattern = r':Sr([-+]?\d{2})\*(\d{2}):(\d{2})#'
    _match_to_hms(pattern, match)

def parse_sd_command(input_str: str):
    pattern = r':Sd([-+]?\d{2})\*(\d{2}):(\d{2})#'
    _match_to_hms(pattern, match)

def _match_to_hms(pattern: str, match: str) -> Tuple[int, int, int]:
    match = re.match(pattern, input_str)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return hours, minutes, seconds
    else:
        return None

def handle_goto_command(ra_parsed, dec_parsed):
    ra_hours, ra_minutes, ra_seconds = ra_parsed
    dec_hours, dec_minutes, dec_seconds = dec_parsed
    logging.debug(f"goto {ra_parsed} {dec_parsed}")

def run_server(shared_state, _):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        logging.info("starting skysafari server")
        server_socket.bind(("", 4030))
        server_socket.listen(1)
        out_data = None
        sr_result = None
        while True:
            client_socket, address = server_socket.accept()
            while True:
                in_data = client_socket.recv(1024).decode()
                if in_data:
                    logging.debug(f"Received from skysafari: {in_data}")
                    if in_data.startswith(":Sr"):
                        parsed_data = parse_sr_command(in_data)
                        if parsed_data:
                            sr_result = parsed_data
                        else:
                            logging.warning("Invalid command format for Sr")
                    elif in_data.startswith(":Sd"):
                        if sr_result:
                            parsed_data = parse_sd_command(in_data)
                            if parsed_data:
                                handle_goto_command(sr_result, parsed_data)
                                out_data = ":Q" # stop the goto
                            else:
                                logging.warning("Invalid command format for Sd")
                        else:
                            logging.warning(":Sd command without preceding :Sr command")
                    elif in_data.startswith(":"):
                        command = in_data[1:].split("#")[0]
                        command_handler = lx_command_dict.get(command, None)
                        if command_handler:
                            out_data = command_handler(shared_state)
                        else:
                            print("Unknown Command:", in_data)
                            out_data = not_implemented(shared_state)
                else:
                    break

                if out_data:
                    client_socket.send(bytes(out_data + "#", "utf-8"))
                    out_data = None
            client_socket.close()

lx_command_dict = {
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "RS": respond_none,
}
