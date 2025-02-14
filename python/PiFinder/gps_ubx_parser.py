#!/usr/bin/env python3

import sys
import json
import math
import logging
from PiFinder.multiproclogging import MultiprocLogging
import asyncio
import aiofiles
from typing import Dict, Callable, Optional, Tuple
from dataclasses import dataclass
from enum import IntEnum
import datetime

logger = logging.getLogger("GPS")


class UBXClass(IntEnum):
    NAV = 0x01
    CFG = 0x06


class NAVMessageId(IntEnum):
    SOL = 0x06
    SVINFO = 0x30
    SAT = 0x35
    TIMEGPS = 0x20
    DOP = 0x04


class CFGMessageId(IntEnum):
    MSG = 0x01
    RATE = 0x08


@dataclass
class ParserConfig:
    enable: bool = True
    json: bool = False
    raw: int = 2


class UBXParser:
    def __init__(
        self,
        log_queue,
        reader: Optional[asyncio.StreamReader] = None,
        writer: Optional[asyncio.StreamWriter] = None,
        file_path: Optional[str] = None,
    ):
        if log_queue is not None:
            MultiprocLogging.configurer(log_queue)
        self.reader = reader
        self.writer = writer
        self.file_path = file_path
        self.config = ParserConfig()
        self.message_parsers: Dict[Tuple[int, int], Callable[[bytes], dict]] = {}
        self.buffer = bytearray()
        self._initialize_parsers()

    def _initialize_parsers(self):
        self._register_parser(UBXClass.NAV, NAVMessageId.SOL, self._parse_nav_sol)
        self._register_parser(UBXClass.NAV, NAVMessageId.SAT, self._parse_nav_sat)
        self._register_parser(
            UBXClass.NAV, NAVMessageId.TIMEGPS, self._parse_nav_timegps
        )
        self._register_parser(UBXClass.NAV, NAVMessageId.DOP, self._parse_nav_dop)
        self._register_parser(UBXClass.NAV, NAVMessageId.SVINFO, self._parse_nav_svinfo)

    def _register_parser(
        self, msg_class: UBXClass, msg_id: int, parser: Callable[[bytes], dict]
    ):
        self.message_parsers[(msg_class, msg_id)] = parser

    def _generate_ubx_message(
        self, msg_class: int, msg_id: int, payload: bytes
    ) -> bytes:
        msg = bytes([msg_class, msg_id]) + len(payload).to_bytes(2, "little") + payload
        ck_a = ck_b = 0
        for b in msg:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        final_msg = b"\xb5\x62" + msg + bytes([ck_a, ck_b])
        # logging.debug(f"Generated message class=0x{msg_class:02x}, id=0x{msg_id:02x}, len={len(payload)}, checksum=0x{ck_a:02x}{ck_b:02x}")
        return final_msg

    async def _handle_initial_messages(self):
        if self.writer is None:
            return

        # Watch command needs proper JSON
        watch_json = json.dumps(
            {
                "enable": True,
                "json": False,
                "raw": 2,
                "binary": True,
                "nmea": False,
                "scaled": False,
                "timing": False,
                "split24": False,
                "pps": False,
                "device": True,
            },
            separators=(",", ":"),
        )
        watch_command = f"?WATCH={watch_json}\r\n"
        self.writer.write(watch_command.encode())
        await self.writer.drain()

    async def _poll_messages(self):
        while True:
            for msg_id in [NAVMessageId.SVINFO, NAVMessageId.TIMEGPS]:
                poll_msg = self._generate_ubx_message(UBXClass.NAV, msg_id, b"")
                # Use bytes.fromhex to create the wrapped message
                prefix = bytes.fromhex("21 31 57 3d")  # !1W=
                suffix = bytes.fromhex("0d 0a")  # \r\n
                wrapped_msg = prefix + poll_msg + suffix

                # logging.debug(f"Raw poll message: {poll_msg.hex()}")
                # logging.debug(f"Wrapped poll message: {wrapped_msg.hex()}")
                self.writer.write(wrapped_msg)
                await self.writer.drain()
            await asyncio.sleep(1)

    @classmethod
    async def connect(cls, log_queue, host="127.0.0.1", port=2947):
        reader, writer = await asyncio.open_connection(host, port)
        parser = cls(log_queue, reader=reader, writer=writer)
        await parser._handle_initial_messages()
        asyncio.create_task(parser._poll_messages())  # Start polling in background
        return parser

    @classmethod
    def from_file(cls, file_path: str):
        return cls(log_queue=None, file_path=file_path)

    async def parse_from_file(self):
        async with aiofiles.open(self.file_path, "rb") as f:
            self.reader = f
            async for msg in self.parse_messages():
                yield msg

    async def parse_messages(self):
        while True:
            if self.reader:
                data = await self.reader.read(1024)
                if not data:
                    break
                # logging.debug(f"Raw data received ({len(data)} bytes): {data.hex()}")
                self.buffer.extend(data)

            while len(self.buffer) >= 6:  # Minimum bytes needed to check length
                # Find UBX header
                start = self.buffer.find(b"\xb5\x62")
                print(f"Header found at {start}")
                if start == -1:
                    self.buffer.clear()
                    break

                if start > 0:
                    self.buffer = self.buffer[start:]

                # Get message length from header
                length = int.from_bytes(self.buffer[4:6], "little")
                total_length = 8 + length  # header (6) + payload + checksum (2)
                # Check if we have the complete message
                if len(self.buffer) < total_length:
                    logging.debug(
                        f"Incomplete message: have {len(self.buffer)}, need {total_length}"
                    )
                    break  # Wait for more data

                # Extract message including checksum
                msg_data = self.buffer[:total_length]

                # Verify checksum
                ck_a = ck_b = 0
                for b in msg_data[2:-2]:  # Skip header and checksum
                    ck_a = (ck_a + b) & 0xFF
                    ck_b = (ck_b + ck_a) & 0xFF

                if msg_data[-2] == ck_a and msg_data[-1] == ck_b:
                    # logging.debug(f"Valid message: class=0x{msg_class:02x}, id=0x{msg_id:02x}, len={length}")
                    parsed = self._parse_ubx(bytes(msg_data))
                    if parsed.get("class"):
                        yield parsed
                else:
                    logging.warning(
                        f"Checksum mismatch: expected {ck_a:02x}{ck_b:02x}, got {msg_data[-2]:02x}{msg_data[-1]:02x}"
                    )

                # Remove processed message from buffer
                self.buffer = self.buffer[total_length:]

            await asyncio.sleep(0)

    def _parse_ubx(self, data: bytes) -> dict:
        if len(data) < 8:
            return {"error": "Invalid UBX message"}
        msg_class = data[2]
        msg_id = data[3]
        length = int.from_bytes(data[4:6], "little")
        payload = data[6 : 6 + length]
        parser = self.message_parsers.get((msg_class, msg_id))
        if parser:
            # logging.debug(f"Found parser for message class=0x{msg_class:02x}, id=0x{msg_id:02x}")
            result = parser(payload)
            return result
        logging.debug(
            f"No parser found for message class=0x{msg_class:02x}, id=0x{msg_id:02x}"
        )
        return {"error": "Unknown message type"}

    def _ecef_to_lla(self, x: float, y: float, z: float):
        a = 6378137.0
        e = 0.0818191908426  # First eccentricity
        p = (x**2 + y**2) ** 0.5
        lat = math.atan2(z, p * (1 - e**2))
        lon = math.atan2(y, x)
        N = a / (1 - e**2 * math.sin(lat) ** 2) ** 0.5
        h = z / math.sin(lat) - N * (1 - e**2)
        return {
            "latitude": math.degrees(lat),
            "longitude": math.degrees(lon),
            "altitude": h,
        }

    def _parse_nav_sol(self, data: bytes) -> dict:
        logger.debug("Parsing nav-sol")
        if len(data) < 52:
            return {"error": "Invalid payload length for nav-sol"}
        gpsFix = data[10]
        ecefX = int.from_bytes(data[12:16], "little", signed=True) / 100.0
        ecefY = int.from_bytes(data[16:20], "little", signed=True) / 100.0
        ecefZ = int.from_bytes(data[20:24], "little", signed=True) / 100.0
        pAcc = int.from_bytes(data[24:28], "little") / 100.0
        numSV = data[47]
        lla = self._ecef_to_lla(ecefX, ecefY, ecefZ)
        result = {
            "class": "NAV-SOL",
            "mode": gpsFix,
            "lat": lla["latitude"],
            "lon": lla["longitude"],
            "altHAE": lla["altitude"],
            "ecefpAcc": pAcc,
            "satellites": numSV,
        }
        logger.debug(f"NAV-SOL result: {result}")
        return result

    def _parse_nav_sat(self, data: bytes) -> dict:
        logger.debug("Parsing nav-sat")
        if len(data) < 8:
            return {"error": "Invalid payload length for nav-sat"}
        numSvs = data[5]
        satellites = []
        for i in range(numSvs):
            offset = 8 + (12 * i)
            if len(data) < offset + 12:
                break
            gnssId = data[offset]
            svId = data[offset + 1]
            cno = data[offset + 2]
            elev = data[offset + 3]
            azim = int.from_bytes(data[offset + 4 : offset + 6], "little")
            flags = data[offset + 11]
            satellites.append(
                {
                    "id": svId,
                    "system": gnssId,
                    "signal": cno,
                    "elevation": elev,
                    "azimuth": azim,
                    "used": bool(flags & 0x08),
                }
            )
        result = {
            "class": "NAV-SAT",
            "nSat": sum(1 for sat in satellites),
            "satellites": satellites,
        }
        logger.debug(f"NAV-SAT result: {result}")
        return result

    def _parse_nav_svinfo(self, data: bytes) -> dict:
        logger.debug("Parsing nav-svinfo")
        if len(data) < 8:
            logger.debug(f"SVINFO: Message too short ({len(data)} bytes)")
            return {"error": "Invalid payload length for nav-svinfo"}

        numCh = data[4]
        globalFlags = data[5]
        logger.debug(f"SVINFO: Number of channels: {numCh}, flags: 0x{globalFlags:02x}")

        satellites = []
        used_sats = 0

        for i in range(numCh):
            offset = 8 + (12 * i)
            if len(data) < offset + 12:
                logger.warning(f"SVINFO: Message truncated at satellite {i}")
                break

            svid = data[offset]
            flags = data[offset + 1]
            quality = data[offset + 2]
            cno = data[offset + 3]
            elev = data[offset + 4]
            azim = int.from_bytes(data[offset + 6 : offset + 8], "little")

            is_used = bool(flags & 0x01)
            if is_used:
                used_sats += 1

            if cno > 0:
                satellites.append(
                    {
                        "id": svid,
                        "signal": cno,
                        "elevation": elev,
                        "azimuth": azim,
                        "used": is_used,
                        "quality": quality,
                    }
                )

        logging.debug(
            f"SVINFO: Processed {len(satellites)} visible satellites, {used_sats} used in fix"
        )

        result = {
            "class": "NAV-SVINFO",
            "nSat": len(satellites),
            "uSat": used_sats,
            "satellites": sorted(satellites, key=lambda x: x["id"]),
        }
        logger.debug(f"NAV-SVINFO result: {result}")
        return result

    def _parse_nav_timegps(self, data: bytes) -> dict:
        logger.debug("Parsing nav-timegps")
        if len(data) < 16:
            return {"error": "Invalid payload length for nav-timegps"}

        iTOW = int.from_bytes(data[0:4], "little")
        fTOW = int.from_bytes(data[4:8], "little")
        week = int.from_bytes(data[8:10], "little", signed=True)
        leapS = data[10]
        valid = data[11]
        tAcc = int.from_bytes(data[12:16], "little")

        gps_epoch = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
        tow = iTOW / 1000.0 + fTOW * 1e-9
        gps_time = (
            gps_epoch + datetime.timedelta(weeks=week) + datetime.timedelta(seconds=tow)
        )
        utc_time = gps_time - datetime.timedelta(seconds=leapS)

        result = {
            "class": "NAV-TIMEGPS",
            "time": utc_time.replace(tzinfo=datetime.timezone.utc),
            "leapSeconds": leapS,
            "valid": bool(valid & 0x01),
            "tAcc": tAcc * 1e-9,
        }
        logging.debug(f"NAV-TIMEGPS result: {result}")
        return result

    def _parse_nav_dop(self, data: bytes) -> dict:
        logging.debug("Parsing nav-dop")
        if len(data) < 18:
            return {"error": "Invalid payload length for nav-dop"}
        result = {
            "class": "NAV-DOP",
            "hdop": int.from_bytes(data[12:14], "little") * 0.01,
            "pdop": int.from_bytes(data[6:8], "little") * 0.01,
        }
        logger.debug(f"NAV-DOP result: {result}")
        return result


if __name__ == "__main__":
    # Parse files stored by gpumon's "l<filename>" command.
    msg_types: dict = {}

    async def test(f_path: str):
        parser = UBXParser.from_file(file_path=f_path)
        async for msg in parser.parse_from_file():
            print(msg)
            msg_type = msg.get("class", "")
            if msg_type != "":
                x = msg_types.get(msg_type, 0) + 1
                msg_types[msg_type] = x

    if len(sys.argv) < 2 or len(sys.argv) > 2:
        print("Usage: python gps_ubx_parser.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]
    asyncio.run(test(file_path))

    print(msg_types)
