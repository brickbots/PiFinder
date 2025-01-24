#!/usr/bin/env python3

import json
import re
import math
import logging
import asyncio
from typing import Dict, Callable, Any, Optional, Tuple, List
from dataclasses import dataclass
from enum import IntEnum
import datetime

logging.basicConfig(level=logging.DEBUG)

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
        reader: Optional[asyncio.StreamReader] = None,
        writer: Optional[asyncio.StreamWriter] = None,
        file_path: Optional[str] = None
    ):
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
        self._register_parser(UBXClass.NAV, NAVMessageId.TIMEGPS, self._parse_nav_timegps)
        self._register_parser(UBXClass.NAV, NAVMessageId.DOP, self._parse_nav_dop)
        self._register_parser(UBXClass.NAV, NAVMessageId.SVINFO, self._parse_nav_svinfo)

    def _register_parser(self, msg_class: UBXClass, msg_id: int, parser: Callable[[bytes], dict]):
        self.message_parsers[(msg_class, msg_id)] = parser

    def _generate_ubx_message(self, msg_class: int, msg_id: int, payload: bytes) -> bytes:
        msg = bytes([msg_class, msg_id]) + len(payload).to_bytes(2, 'little') + payload
        ck_a = ck_b = 0
        for b in msg:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return b'\xB5\x62' + msg + bytes([ck_a, ck_b])

    async def _handle_initial_messages(self):
        if self.writer is None:
            return
        watch_command = b'?WATCH={"enable":true,"json":false,"raw":2}\n'
        self.writer.write(watch_command)
        await self.writer.drain()
        cfg_msg_sat = self._generate_ubx_message(
            UBXClass.CFG, CFGMessageId.MSG,
            bytes([UBXClass.NAV, NAVMessageId.SAT, 0x01])
        )
        self.writer.write(cfg_msg_sat)
        await self.writer.drain()
        cfg_msg_svinfo = self._generate_ubx_message(
            UBXClass.CFG, CFGMessageId.MSG,
            bytes([UBXClass.NAV, NAVMessageId.SVINFO, 0x01])
        )
        self.writer.write(cfg_msg_svinfo)
        await self.writer.drain()
        poll_sat = self._generate_ubx_message(UBXClass.NAV, NAVMessageId.SAT, b'')
        self.writer.write(poll_sat)
        await self.writer.drain()
        poll_svinfo = self._generate_ubx_message(UBXClass.NAV, NAVMessageId.SVINFO, b'')
        self.writer.write(poll_svinfo)
        await self.writer.drain()

    @classmethod
    async def connect(cls, host='127.0.0.1', port=2947):
        reader, writer = await asyncio.open_connection(host, port)
        parser = cls(reader=reader, writer=writer)
        await parser._handle_initial_messages()
        return parser

    @classmethod
    def from_file(cls, file_path: str):
        return cls(file_path=file_path)

    async def parse_messages(self):
        while True:
            if self.reader:
                data = await self.reader.read(1024)
                if not data:
                    break
                self.buffer.extend(data)
            elif self.file_path:
                if not self.buffer:
                    with open(self.file_path, 'rb') as f:
                        self.buffer = bytearray(f.read())
                else:
                    await asyncio.sleep(0.1)
            else:
                break

            while True:
                start = self.buffer.find(b'\xB5\x62')
                if start == -1:
                    self.buffer = bytearray()
                    break
                if start > 0:
                    self.buffer = self.buffer[start:]
                    start = 0
                if len(self.buffer) < 8:
                    break
                msg_class = self.buffer[2]
                msg_id = self.buffer[3]
                length = int.from_bytes(self.buffer[4:6], 'little')
                total_length = 8 + length + 2
                if len(self.buffer) < total_length:
                    break
                msg_data = bytes(self.buffer[:total_length])
                self.buffer = self.buffer[total_length:]
                parsed = self._parse_ubx(msg_data)
                if parsed.get('class'):
                    yield parsed
            if self.file_path and not self.buffer:
                break
            await asyncio.sleep(0)

    def _parse_ubx(self, data: bytes) -> dict:
        if len(data) < 8:
            return {"error": "Invalid UBX message"}
        msg_class = data[2]
        msg_id = data[3]
        length = int.from_bytes(data[4:6], 'little')
        payload = data[6:6+length]
        parser = self.message_parsers.get((msg_class, msg_id))
        if parser:
            result = parser(payload)
            return result
        return {"error": "Unknown message type"}

    def _ecef_to_lla(self, x: float, y: float, z: float):
        a = 6378137.0
        f = 1/298.257223563
        b = a * (1 - f)
        e = (a**2 - b**2)**0.5 / a
        p = (x**2 + y**2)**0.5
        theta = math.atan2(z*a, p*b)
        lon = math.atan2(y, x)
        lat = math.atan2(
            z + e**2 * b * math.sin(theta)**3,
            p - e**2 * a * math.cos(theta)**3
        )
        N = a / (1 - e**2 * math.sin(lat)**2)**0.5
        alt = p / math.cos(lat) - N
        return {
            "latitude": math.degrees(lat),
            "longitude": math.degrees(lon),
            "altitude": alt
        }

    def _parse_nav_sol(self, data: bytes) -> dict:
        if len(data) < 52:
            return {"error": "Invalid payload length"}
        gpsFix = data[10]
        ecefX = int.from_bytes(data[12:16], 'little', signed=True) / 100.0
        ecefY = int.from_bytes(data[16:20], 'little', signed=True) / 100.0
        ecefZ = int.from_bytes(data[20:24], 'little', signed=True) / 100.0
        pAcc = int.from_bytes(data[24:28], 'little') / 100.0
        numSV = data[47]
        lla = self._ecef_to_lla(ecefX, ecefY, ecefZ)
        return {
            "class": "TPV",
            "mode": gpsFix,
            "lat": lla["latitude"],
            "lon": lla["longitude"],
            "altHAE": lla["altitude"],
            "ecefpAcc": pAcc,
            "satellites": numSV
        }

    def _parse_nav_sat(self, data: bytes) -> dict:
        if len(data) < 8:
            return {"error": "Invalid payload length"}
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
            azim = int.from_bytes(data[offset+4:offset+6], 'little')
            flags = data[offset + 11]
            satellites.append({
                "id": svId,
                "system": gnssId,
                "signal": cno,
                "elevation": elev,
                "azimuth": azim,
                "used": bool(flags & 0x08)
            })
        return {
            "class": "SKY",
            "nSat": numSvs,
            "uSat": sum(1 for sat in satellites if sat["used"]),
            "satellites": satellites
        }

    def _parse_nav_svinfo(self, data: bytes) -> dict:
        if len(data) < 8:
            return {"error": "Invalid payload length"}
        numCh = int.from_bytes(data[4:6], 'little')
        satellites = []
        for i in range(numCh):
            offset = 8 + (12 * i)
            if len(data) < offset + 12:
                break
            svid = data[offset]
            flags = data[offset + 1]
            cno = data[offset + 3]
            elev = data[offset + 4]
            azim = int.from_bytes(data[offset+6:offset+8], 'little')
            satellites.append({
                "id": svid,
                "signal": cno,
                "elevation": elev,
                "azimuth": azim,
                "used": bool(flags & 0x01)
            })
        return {
            "class": "SKY",
            "nSat": numCh,
            "uSat": sum(1 for sat in satellites if sat["used"]),
            "satellites": satellites
        }

    def _parse_nav_timegps(self, data: bytes) -> dict:
        if len(data) < 16:
            return {"error": "Invalid payload length"}
        iTOW = int.from_bytes(data[0:4], 'little')
        week = int.from_bytes(data[8:10], 'little', signed=True)
        leapS = data[10]
        gps_epoch = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
        tow = iTOW / 1000.0
        gps_time = gps_epoch + datetime.timedelta(weeks=week) + datetime.timedelta(seconds=tow)
        utc_time = gps_time - datetime.timedelta(seconds=leapS)
        return {
            "class": "TPV",
            "time": utc_time.replace(tzinfo=datetime.timezone.utc)
        }

    def _parse_nav_dop(self, data: bytes) -> dict:
        if len(data) < 18:
            return {"error": "Invalid payload length"}
        return {
            "class": "SKY",
            "hdop": int.from_bytes(data[12:14], 'little') * 0.01,
            "pdop": int.from_bytes(data[6:8], 'little') * 0.01
        }

if __name__ == "__main__":
    async def test():
        parser = UBXParser.from_file("captured.ubx")
        async for msg in parser.parse_messages():
            print(msg)
    asyncio.run(test())
