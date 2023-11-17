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
from PiFinder import calc_utils
from skyfield.positionlib import position_of_radec
from skyfield.api import load

skyfield_ts = load.timescale()


def get_telescope_ra(shared_state):
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
    _p = position_of_radec(
        ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=skyfield_ts.J2000
    )

    RA_h, Dec, _dist = _p.radec(epoch=skyfield_ts.now())

    hh, mm, ss = RA_h.hms()
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

    # Convert from J2000 to now epoch
    RA_deg = solution["RA"]
    Dec_deg = solution["Dec"]
    _p = position_of_radec(
        ra_hours=RA_deg / 15.0, dec_degrees=Dec_deg, epoch=skyfield_ts.J2000
    )

    RA_h, Dec, _dist = _p.radec(epoch=skyfield_ts.now())

    dec = Dec.degrees

    mm, hh = modf(dec)
    fractional_mm, mm = modf(mm * 60.0)
    ss = round(fractional_mm * 60.0)

    if dec < 0:
        dec = abs(dec)
        sign = "-"
    else:
        sign = "+"
    return f"{sign}{hh:02.0f}*{mm:02.0f}'{ss:02.0f}"


def respond_none(shared_state):
    return None


def not_implemented(shared_state):
    return "not implemented"


def run_server(shared_state, _):
    """
    Answers request with info from shared state
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        # 4030 seems to be the default in SkySafari
        server_socket.bind(("", 4030))
        server_socket.listen(1)
        out_data = None
        while True:
            client_socket, address = server_socket.accept()
            while True:
                try:
                    in_data = client_socket.recv(1024).decode()
                except ConnectionResetError:
                    client_socket.close()
                    out_data = None
                    in_data = None

                if in_data:
                    if in_data == "\x06":
                        # Ack, reply with 'A' for alt-az mode
                        out_data = "A"
                    if in_data.startswith(":"):
                        # command
                        command = in_data[1:].split("#")[0]
                        command_handler = lx_command_dict.get(command, None)
                        if command_handler:
                            out_data = command_handler(shared_state)
                        else:
                            print("Unkown Command:", in_data)
                            out_data = not_implemented(shared_state)

                        if out_data:
                            # Command replies should be terminated with #
                            out_data += "#"
                else:
                    break

                if out_data:
                    client_socket.send(bytes(out_data, "utf-8"))
                    out_data = None
            client_socket.close()


lx_command_dict = {
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "RS": respond_none,
}
