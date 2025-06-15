#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Client for the StarParty platform
"""

from dataclasses import dataclass, field
import asyncio
from asyncio import StreamReader, StreamWriter
from typing import Union
import contextlib

from PIL import Image, ImageDraw, ImageOps, ImageChops

from StarParty.sps_data import Position, GroupActivity, calc_avatar_bits


def generate_avatar_image(avatar_bits: int) -> Image.Image:
    """
    Returns an 8x8 image for the provided avatar_bits
    """
    work_image = Image.new("RGB", (8, 8))
    drawer = ImageDraw.Draw(work_image)
    bit_string = bin(avatar_bits)[2:].zfill(32)
    for line in range(8):
        for bit in range(4):
            if bit_string[line * 4 + bit] == "1":
                drawer.point((bit, line), fill=(255, 255, 255))

    # mirror
    mirror_image = ImageOps.mirror(work_image)

    # add
    return ImageChops.add(work_image, mirror_image)


@dataclass
class ClientObserver:
    name: str
    avatar_bits: int
    avatar_image: Union[Image.Image, None] = None
    group: Union[str, None] = None
    position: Position = field(default_factory=Position)

    def __str__(self):
        return self.name

    def __post_init__(self):
        # compute the avatar image
        self.avatar_image = generate_avatar_image(self.avatar_bits)

    @classmethod
    def deserialize(cls, observer_raw: str) -> "ClientObserver":
        _observer_split = observer_raw.split("|")
        return cls(
            name=_observer_split[0],
            avatar_bits=int(_observer_split[1]),
            group=_observer_split[2],
            position=Position.deserialize(_observer_split[3]),
        )


@dataclass
class ClientGroup:
    name: str
    activity: GroupActivity
    observer_count: int

    @classmethod
    def deserialize(cls, group_raw: str) -> "ClientGroup":
        _group_split = group_raw.split("|")
        return cls(
            name=_group_split[0],
            activity=GroupActivity(_group_split[1]),
            observer_count=int(_group_split[2]),
        )


class SPClient:
    def __init__(self) -> None:
        self.reader: Union[StreamReader, None] = None
        self.writer: Union[StreamWriter, None] = None
        self.group_observers: list[ClientObserver] = []
        self.connected: bool = False
        self.current_group: Union[ClientGroup, None] = None
        self.username: Union[str, None] = None

        self._reader_task: Union[asyncio.Task, None] = None
        self._state_lock = asyncio.Lock()

    async def connect(self, username: str, host: str, port: int = 8728) -> bool:
        async with self._state_lock:
            # Create A queue of Futures for awaiting responses and a lock
            self._pending_responses: asyncio.Queue[asyncio.Future[str]] = (
                asyncio.Queue()
            )

            self.username = username
            self.avatar_bits = calc_avatar_bits(username)
            self.avatar_image = generate_avatar_image(self.avatar_bits)
            self.reader, self.writer = await asyncio.open_connection(host, port)
            self._reader_task = asyncio.create_task(self._listen_for_messages())
            self.connected = True
            print("Connected to server")
            resp = await self.send_command(f"name|{username}")
            if resp == "ack":
                return True
            else:
                return False

    async def disconnect(self) -> None:
        async with self._state_lock:
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
            if self._reader_task:
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task
            self.connected = False

    async def join_group(self, group_name) -> bool:
        async with self._state_lock:
            resp = await self.send_command(f"join|{group_name}")
            if resp == "err":
                return False

            # if we get here, the first line of the response will be
            # the group info, then observers in the group

            # split and drop the ack from the response
            print(f"Joined group\n{resp}=====")
            resp_lines = resp.split("\n")[:-1]
            self.current_group = ClientGroup.deserialize(resp_lines[0])

            # populate observers
            self.group_observers = [
                ClientObserver.deserialize(x) for x in resp_lines[1:]
            ]
            print(self.group_observers)

            return True

    async def leave_group(self) -> bool:
        async with self._state_lock:
            resp = await self.send_command("leave")
            if resp == "err":
                return False

            self.current_group = None
            self.group_observers = []
            return True

    async def list_groups(self) -> list[ClientGroup]:
        resp = await self.send_command("groups")
        if resp == "err":
            return []

        if not resp:
            return []

        groups_raw = resp.split("\n")
        return [ClientGroup.deserialize(x) for x in groups_raw]

    async def _listen_for_messages(self) -> None:
        assert self.reader is not None

        current_response_lines: list[str] = []
        current_future: Union[asyncio.Future[str], None] = None

        try:
            while True:
                raw_line = await self.reader.readline()
                if not raw_line:
                    print("Server closed connection")
                    break

                line = raw_line.decode().rstrip("\n")

                if line.startswith("\t"):
                    # strip tab
                    line = line.strip()
                    if current_future is None:
                        current_future = await self._pending_responses.get()

                    if line == "ack":
                        full_response = "\n".join(current_response_lines)
                        current_future.set_result(full_response)
                        current_response_lines = []
                        current_future = None
                    elif line == "err":
                        full_response = "err"
                        current_future.set_result(full_response)
                        current_response_lines = []
                        current_future = None
                    else:
                        current_response_lines.append(line)
                else:
                    await self._handle_event(line)

        except Exception as e:
            print(f"Reader error: {e}")
            # Optionally set exception on any pending future
            if current_future and not current_future.done():
                current_future.set_exception(e)

    async def _handle_event(self, message: str):
        print(f"[Event] {message}")

    async def send_command(self, cmd: str, timeout: float = 5.0) -> str:
        if not self.writer:
            raise RuntimeError("Client not connected")

        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        await self._pending_responses.put(future)

        self.writer.write((cmd + "\n").encode())
        await self.writer.drain()

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"No response received for command: {cmd!r}")

    async def get_state(self):
        async with self._state_lock:
            return dict(self._state)
