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

logger = logging.getLogger("GPS.parser")


class UBXClass(IntEnum):
    NAV = 0x01
    CFG = 0x06


class NAVMessageId(IntEnum):
    # U7 Messages (standard GPS as in the build guide), see https://content.u-blox.com/sites/default/files/products/documents/u-blox7-V14_ReceiverDescriptionProtocolSpec_%28GPS.G7-SW-12001%29_Public.pdf
    SOL = 0x06
    SVINFO = 0x30
    SAT = 0x35
    TIMEGPS = 0x20
    DOP = 0x04
    # For EOE, PVT and POSECEF see https://www.u-blox.com/docs/UBX-20053845 for specification of the messages
    # (search for 0x01 0xMM)
    EOE = 0x61  # End of Epoch
    PVT = 0x07  # Position Velocity Time
    POSECEF = 0x01  # Position solution in ECEF


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
        self._poll_task = None  # Store polling task for cleanup
        self._running = True  # Control flag for polling loop
        self._initialize_parsers()

    def _initialize_parsers(self):
        self._register_parser(UBXClass.NAV, NAVMessageId.SOL, self._parse_nav_sol)
        self._register_parser(UBXClass.NAV, NAVMessageId.SAT, self._parse_nav_sat)
        self._register_parser(
            UBXClass.NAV, NAVMessageId.TIMEGPS, self._parse_nav_timegps
        )
        self._register_parser(UBXClass.NAV, NAVMessageId.DOP, self._parse_nav_dop)
        self._register_parser(UBXClass.NAV, NAVMessageId.SVINFO, self._parse_nav_svinfo)
        self._register_parser(UBXClass.NAV, NAVMessageId.PVT, self._parse_nav_pvt)
        self._register_parser(
            UBXClass.NAV, NAVMessageId.POSECEF, self._parse_nav_posecef
        )
        self._register_parser(UBXClass.NAV, NAVMessageId.EOE, self._parse_nav_eoe)

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
        return final_msg

    async def _handle_initial_messages(self):
        if self.writer is None or self.writer.is_closing():
            logger.warning("Writer unavailable for initial messages")
            return

        watch_json = json.dumps(
            {"enable": True, "raw": 2, "json": False, "binary": True, "nmea": False},
            separators=(",", ":"),
        )
        watch_command = f"?WATCH={watch_json}\r\n"
        logger.debug(f"Sending WATCH command: {watch_command}")
        self.writer.write(watch_command.encode())
        await self.writer.drain()
        # Optional: Read response to confirm
        response = await self.reader.read(1024)
        logger.debug(f"WATCH response: {response.decode('utf-8', errors='ignore')}")

    async def _poll_messages(self):
        # while self._running and self.writer and not self.writer.is_closing():
        #     try:
        #         for msg_id in [NAVMessageId.SVINFO, NAVMessageId.TIMEGPS]:
        #             poll_msg = self._generate_ubx_message(UBXClass.NAV, msg_id, b"")
        #             prefix = bytes.fromhex("21 31 57 3d")  # !1W=
        #             suffix = bytes.fromhex("0d 0a")  # \r\n
        #             wrapped_msg = prefix + poll_msg + suffix
        #             self.writer.write(wrapped_msg)
        #             await self.writer.drain()
        #         await asyncio.sleep(1)
        #     except (ConnectionResetError, BrokenPipeError, AttributeError) as e:
        #         logger.error(f"Polling error: {e}. Stopping polling.")
        #         self._running = False
        #         break
        pass

    @classmethod
    async def connect(cls, log_queue, host="127.0.0.1", port=2947, max_attempts=5):
        attempt = 0
        while attempt < max_attempts:
            try:
                # Add delay between connection attempts
                if attempt > 0:
                    delay = min(2**attempt, 30)
                    logger.error(
                        f"Connection attempt {attempt}/{max_attempts} failed. Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)

                reader, writer = await asyncio.open_connection(host, port)
                parser = cls(log_queue, reader=reader, writer=writer)
                await parser._handle_initial_messages()
                return parser
            except (ConnectionRefusedError, ConnectionResetError) as e:
                attempt += 1
                if attempt >= max_attempts:
                    logger.error(
                        f"Failed to connect after {max_attempts} attempts: {e}"
                    )
                    raise

    @classmethod
    async def from_file(cls, file_path: str):
        """Create a UBXParser instance from a file."""
        f = await aiofiles.open(file_path, "rb")
        return cls(log_queue=None, reader=f, file_path=file_path)  # type:ignore[arg-type]

    async def close(self):
        """Clean up resources and close the connection."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                logger.debug("Polling task cancelled")
            self._poll_task = None
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logger.error(f"Error closing writer: {e}")
            finally:
                self.writer = None
        self.reader = None
        self.buffer.clear()  # Clear any remaining data

    async def parse_messages(self):
        """Parse messages from the GPS device."""
        while self._running:
            try:
                if not self.reader:
                    logger.error("Reader not available")
                    break

                data = await self.reader.read(1024)
                if not data:
                    logger.warning("Read failed. Connection closed by server")
                    break

                self.buffer.extend(data)
                while len(self.buffer) >= 6:  # Minimum UBX header size
                    start = self.buffer.find(b"\xb5\x62")  # UBX sync chars
                    if start == -1:
                        logger.debug("No UBX header found, clearing buffer")
                        self.buffer.clear()
                        break
                    if start > 0:
                        self.buffer = self.buffer[start:]
                    length = int.from_bytes(self.buffer[4:6], "little")
                    total_length = 8 + length  # Header (6) + checksum (2) + payload
                    if len(self.buffer) < total_length:
                        break
                    msg_data = self.buffer[:total_length]
                    ck_a = ck_b = 0
                    for b in msg_data[2:-2]:  # Skip sync and checksum
                        ck_a = (ck_a + b) & 0xFF
                        ck_b = (ck_b + ck_a) & 0xFF
                    if msg_data[-2] == ck_a and msg_data[-1] == ck_b:
                        parsed = self._parse_ubx(bytes(msg_data))
                        if "class" in parsed:
                            logger.debug(f"Parsed UBX message: {parsed}")
                            yield parsed
                    else:
                        logger.warning(
                            f"Checksum mismatch: expected {ck_a:02x}{ck_b:02x}, got {msg_data[-2]:02x}{msg_data[-1]:02x}"
                        )
                    self.buffer = self.buffer[total_length:]
            except (ConnectionResetError, BrokenPipeError):
                logger.exception("Connection error")
                break
            except Exception:
                logger.exception("Error reading data.")
                break

            await asyncio.sleep(0.1)  # Prevent tight loop

        # Ensure cleanup when loop ends
        await self.close()

    def _parse_ubx(self, data: bytes) -> dict:
        if len(data) < 8:
            return {"error": "Invalid UBX message"}
        msg_class = data[2]
        msg_id = data[3]
        length = int.from_bytes(data[4:6], "little")
        payload = data[6 : 6 + length]
        parser = self.message_parsers.get((msg_class, msg_id))
        if parser:
            result = parser(payload)
            return result
        logger.debug(
            f"No parser found for message class=0x{msg_class:02x}, id=0x{msg_id:02x}"
        )
        return {"error": "Unknown message type"}

    def _ecef_to_lla(self, x: float, y: float, z: float):
        try:
            a = 6378137.0
            e = 0.0818191908426
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
        except Exception as e:
            logger.error(f"Error converting ECEF to LLA: {e}, x: {x}, y: {y}, z: {z}")
            return {"error": "Invalid ECEF coordinates"}

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
        result = {}
        if ecefX == 0 or ecefY == 0 or ecefZ == 0:
            logger.debug(
                f"nav_sol zeroes: ecefX: {ecefX}, ecefY: {ecefY}, ecefZ: {ecefZ}, pAcc: {pAcc}, numSV: {numSV}"
            )
        else:
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
            logger.error("NAV-SAT: Message too short")
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
            flags = data[
                offset + 8
            ]  # Warning this is a 4 byte field of flags, we're only using the first byte
            # lowest 3 bits are a quality indicator and according to
            # https://portal.u-blox.com/s/question/0D52p000097B0bFCAS/interpretation-of-signal-quality-indicator-in-ubxnavsat
            # the 0-7 values from an ordered scale. So taking 3 as the threshold below.q
            satellites.append(
                {
                    "id": svId,
                    "system": gnssId,
                    "signal": cno,
                    "elevation": elev,
                    "azimuth": azim,
                    "used": (flags & 0x07) > 3,  # lowest 3 bits are used for the status
                    "flags": flags & 0x07,
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
            logger.warning(f"SVINFO: Message too short ({len(data)} bytes)")
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

        logger.debug(
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
        logger.debug(f"NAV-TIMEGPS result: {result}")
        return result

    def _parse_nav_dop(self, data: bytes) -> dict:
        logger.debug("Parsing nav-dop")
        if len(data) < 18:
            logger.error("NAV-DOP: Message too short")
            return {"error": "Invalid payload length for nav-dop"}
        result = {
            "class": "NAV-DOP",
            "hdop": int.from_bytes(data[12:14], "little") * 0.01,
            "pdop": int.from_bytes(data[6:8], "little") * 0.01,
        }
        logger.debug(f"NAV-DOP result: {result}")
        return result

    def _parse_nav_posecef(self, data: bytes) -> dict:
        """Position solution in ECEF"""
        logger.debug("Parsing nav-posecef")
        if len(data) < 20:
            return {"error": "Invalid payload length for nav-posecef"}
        ecefX = int.from_bytes(data[4:8], "little", signed=True) / 100.0
        ecefY = int.from_bytes(data[8:12], "little", signed=True) / 100.0
        ecefZ = int.from_bytes(data[12:16], "little", signed=True) / 100.0
        result = {}
        if ecefX == 0 or ecefY == 0 or ecefZ == 0:
            logger.debug(
                f"nav_posecef zeroes: ecefX: {ecefX}, ecefY: {ecefY}, ecefZ: {ecefZ}"
            )
        else:
            lla = self._ecef_to_lla(ecefX, ecefY, ecefZ)
            result = {
                "class": "NAV-POSECEF",
                "lat": lla["latitude"],
                "lon": lla["longitude"],
                "altHAE": lla["altitude"],
            }
        logger.debug(f"NAV-POSECEF result: {result}")
        return result

    def _parse_nav_pvt(self, data: bytes) -> dict:
        """This message combines position, velocity and time solution, including accuracy figures.
        Note that during a leap second there may be more or less than 60 seconds in a minute."""

        logger.debug("Parsing nav-pvt")
        if len(data) < 90:
            return {"error": "Invalid payload length for nav-pvt"}
        year = int.from_bytes(data[4:6], "little", signed=False)
        month = data[6]
        day = data[7]
        hour = data[8]
        minute = data[9]
        seconds = data[10]
        tAcc = int.from_bytes(data[24:28], "little", signed=False) / 1e9  # nano seconds
        nano = int.from_bytes(data[24:28], "little", signed=True) / 1e9  # nano seconds
        gpsFix = data[20]
        numSV = data[23]
        lon = int.from_bytes(data[24:28], "little", signed=True) / 1e7
        lat = int.from_bytes(data[28:32], "little", signed=True) / 1e7
        height = (
            int.from_bytes(data[32:36], "little", signed=True) / 1000.0
        )  # Height above ellipsoid / m
        hMSL = (
            int.from_bytes(data[36:40], "little", signed=True) / 1000.0
        )  # Main Sea Level / m
        hAcc = (
            int.from_bytes(data[40:44], "little", signed=False) / 1000.0
        )  # horizontal Accurary / m
        vAcc = (
            int.from_bytes(data[44:48], "little", signed=False) / 1000.0
        )  # vertical Accuracy / m
        pDOP = (
            int.from_bytes(data[76:78], "little", signed=False) / 100.0
        )  # position DOP

        result = {
            "class": "NAV-PVT",
            "UTCyear": year,
            "UTCmonth": month,
            "UTCday": day,
            "UTChour": hour,
            "UTCminute": minute,
            "UTCseconds": seconds,
            "UTCnano": nano,
            "tAcc": tAcc,
            "mode": gpsFix,
            "lat": lat,
            "lon": lon,
            "altHAE": height,
            "hMSL": hMSL,
            "numSV": numSV,
            "hAcc": hAcc,
            "vAcc": vAcc,
            "pDOP": pDOP,
        }
        logger.debug(f"NAV-PVT result: {result}")
        return result

    def _parse_nav_eoe(self, data: bytes) -> dict:
        logger.debug("Ignoring nav-eoe")
        if len(data) < 4:
            return {"error": "Invalid payload length for nav-pvt"}
        # The End of Epoch message consists of an iTOW Time only
        return {"class": "NAV-EOE"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    # Remove processed message from buffer
    msg_types: dict = {}

    async def test(f_path: str = ""):
        if f_path:
            parser = await UBXParser.from_file(file_path=f_path)
            i = 0
            try:
                async for msg in parser.parse_messages():
                    print(msg)
                    msg_type = msg.get("class", "")
                    if msg_type != "":
                        msg_types[msg_type] = msg_types.get(msg_type, 0) + 1
                    i += 1
                    if i % 1000 == 0:
                        print(".", end="", flush=True)
            finally:
                await parser.close()
                print(f"\nTotal messages processed: {i}")
        else:
            parser = await UBXParser.connect(log_queue=None)
            try:
                async for msg in parser.parse_messages():
                    # print(msg)
                    if "error" in msg:
                        error_msg = msg.get("error")
                        msg_types[error_msg] = msg_types.get(error_msg, 0) + 1
                    else:
                        msg_type = msg.get("class", "")
                        if msg_type != "":
                            msg_types[msg_type] = msg_types.get(msg_type, 0) + 1
            finally:
                await parser.close()

    try:
        if len(sys.argv) < 2 or len(sys.argv) > 2:
            print("Usage: python gps_ubx_parser.py <file_path> (optional)")
            asyncio.run(test())
        else:
            file_path = sys.argv[1]
            asyncio.run(test(file_path))
    except KeyboardInterrupt:
        print("Keyboard Interrupt received.")

    print(msg_types)
