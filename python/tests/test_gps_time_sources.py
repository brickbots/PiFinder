import asyncio
import datetime
from queue import Queue

import pytz

from PiFinder.gps_gpsd import gpsd_sky_time_sample, gpsd_time_message
from PiFinder.gps_ubx import process_messages
from PiFinder.gps_ubx_parser import UBXParser


def test_gpsd_time_message_does_not_require_position_lock():
    gps_time = datetime.datetime(2026, 1, 1, 1, 2, 3, tzinfo=pytz.UTC)

    msg = gpsd_time_message({"time": gps_time, "mode": 1}, gps_locked=False)

    assert msg == (
        "time",
        {
            "time": gps_time,
            "source": "GPSD",
            "mode": 1,
            "lock": False,
        },
    )


def test_gpsd_sky_time_is_monitor_only_sample():
    gps_time = datetime.datetime(2019, 4, 7, 14, 37, 23, tzinfo=pytz.UTC)

    msg = gpsd_sky_time_sample(
        {
            "time": gps_time,
            "nSat": 1,
            "uSat": 0,
            "hdop": 99.99,
            "pdop": 99.99,
        }
    )

    assert msg == (
        "time_sample",
        {
            "time": gps_time,
            "source": "GPSD-SKY",
            "valid": False,
            "satellites_seen": 1,
            "satellites_used": 0,
            "hdop": 99.99,
            "pdop": 99.99,
        },
    )


def test_nav_pvt_parser_extracts_time_and_accuracy_from_correct_offsets():
    payload = bytearray(92)
    payload[4:6] = (2026).to_bytes(2, "little")
    payload[6] = 2
    payload[7] = 3
    payload[8] = 4
    payload[9] = 5
    payload[10] = 6
    payload[11] = 0x03
    payload[12:16] = (25_000_000).to_bytes(4, "little")
    payload[16:20] = (123_000_000).to_bytes(4, "little", signed=True)
    payload[20] = 0
    payload[23] = 7
    payload[24:28] = int(127.1234567 * 1e7).to_bytes(4, "little", signed=True)
    payload[28:32] = int(37.1234567 * 1e7).to_bytes(4, "little", signed=True)
    payload[32:36] = int(42_000).to_bytes(4, "little", signed=True)
    payload[36:40] = int(41_000).to_bytes(4, "little", signed=True)
    payload[40:44] = int(1500).to_bytes(4, "little")
    payload[44:48] = int(2000).to_bytes(4, "little")
    payload[76:78] = int(1.25 * 100).to_bytes(2, "little")

    parsed = UBXParser(log_queue=None)._parse_nav_pvt(bytes(payload))

    assert parsed["valid"] is True
    assert parsed["time"] == datetime.datetime(
        2026, 2, 3, 4, 5, 6, 123000, tzinfo=datetime.timezone.utc
    )
    assert parsed["tAcc_ns"] == 25_000_000
    assert parsed["UTCnano"] == 123_000_000
    assert parsed["mode"] == 0
    assert parsed["numSV"] == 7


def test_nav_pvt_parser_keeps_invalid_time_as_candidate():
    payload = bytearray(92)
    payload[4:6] = (2021).to_bytes(2, "little")
    payload[6] = 3
    payload[7] = 7
    payload[8] = 14
    payload[9] = 37
    payload[10] = 25
    payload[11] = 0xF0

    parsed = UBXParser(log_queue=None)._parse_nav_pvt(bytes(payload))

    assert parsed["valid"] is False
    assert parsed["time"] == datetime.datetime(
        2021, 3, 7, 14, 37, 25, tzinfo=datetime.timezone.utc
    )


def test_ubx_process_messages_emits_nav_pvt_time_before_position_fix():
    gps_time = datetime.datetime(2026, 1, 1, 1, 2, 3, tzinfo=datetime.timezone.utc)

    async def stream():
        yield {
            "class": "NAV-PVT",
            "time": gps_time,
            "valid": True,
            "tAcc_ns": 50_000_000,
            "mode": 0,
            "lat": 37.0,
            "lon": 127.0,
            "altHAE": 42.0,
            "hAcc": 99_999.0,
            "vAcc": 99_999.0,
        }

    gps_queue = Queue()
    console_queue = Queue()
    asyncio.run(
        process_messages(
            lambda: stream(),
            gps_queue,
            console_queue,
            {"error_2d": 999, "error_3d": 999},
        )
    )

    gps_msg, gps_content = gps_queue.get_nowait()
    assert gps_msg == "time"
    assert gps_content["time"] == gps_time
    assert gps_content["tAcc"] == 50_000_000
    assert gps_content["message_class"] == "NAV-PVT"


def test_ubx_process_messages_emits_invalid_nav_pvt_time_as_sample():
    gps_time = datetime.datetime(2021, 3, 7, 14, 37, 25, tzinfo=datetime.timezone.utc)

    async def stream():
        yield {
            "class": "NAV-PVT",
            "time": gps_time,
            "valid": False,
            "tAcc_ns": -1,
            "mode": 0,
        }

    gps_queue = Queue()
    console_queue = Queue()
    asyncio.run(
        process_messages(
            lambda: stream(),
            gps_queue,
            console_queue,
            {"error_2d": 999, "error_3d": 999},
        )
    )

    gps_msg, gps_content = gps_queue.get_nowait()
    assert gps_msg == "time_sample"
    assert gps_content["time"] == gps_time
    assert gps_content["valid"] is False
