#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Client for the StarParty platform
"""

from dataclasses import dataclass, field
import asyncio
import socket  # for exception
from asyncio import StreamReader, StreamWriter
from typing import Union
from collections import deque
import contextlib

from PIL import Image, ImageDraw, ImageOps, ImageChops

from StarParty.sps_data import Position, GroupActivity, calc_avatar_bits, EventType


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
class CommandResponse:
    status: str
    payload: list[str]

    def __bool__(self) -> bool:
        if self.status in ["ack"]:
            return True
        else:
            return False


@dataclass
class ClientEvent:
    event_type: EventType
    payload: tuple[str, ...]


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
class ClientObserverList:
    """
    List of client observers with helpers
    for adding, removing, updating
    """

    observers: dict[str, ClientObserver] = field(default_factory=dict)

    def __str__(self):
        return str(self.observers)

    def add(self, observer: ClientObserver) -> None:
        self.observers[observer.name] = observer

    def remove(self, observer_name: str) -> None:
        try:
            del self.observers[observer_name]
        except KeyError:
            pass

    def update_pos(self, observer_name: str, ra: float, dec: float) -> None:
        try:
            self.observers[observer_name].position = Position(ra=ra, dec=dec)
        except KeyError:
            pass

    def as_list(self, exclude_name: str = "") -> list[ClientObserver]:
        """
        Returns a list of observers, excluding
        a particualr observer by name if provided
        """
        return_list: list[ClientObserver] = []
        for observer in self.observers.values():
            if observer.name != exclude_name:
                return_list.append(observer)
        return return_list

    @classmethod
    def from_list(cls, observer_list: list[ClientObserver]) -> "ClientObserverList":
        return cls(observers={x.name: x for x in observer_list})


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
        self.group_observers: ClientObserverList = ClientObserverList()
        self.connected: bool = False
        self.current_group: Union[ClientGroup, None] = None
        self.username: Union[str, None] = None

        self._reader_task: Union[asyncio.Task, None] = None
        self._state_lock = asyncio.Lock()

        self._public_events: deque[ClientEvent] = deque(maxlen=2)

    def publish_event(self, event: ClientEvent) -> None:
        self._public_events.append(event)

    def get_next_event(self) -> Union[ClientEvent, None]:
        """
        Returns the next oldest event after event_time
        or None if no event is older than the requested
        time
        """
        try:
            return self._public_events.pop()
        except IndexError:
            return None

    async def connect(self, username: str, host: str, port: int = 8728) -> bool:
        async with self._state_lock:
            # Create A queue of Futures for awaiting responses
            self._pending_responses: asyncio.Queue[asyncio.Future[CommandResponse]] = (
                asyncio.Queue()
            )

            self.username = username
            self.avatar_bits = calc_avatar_bits(username)
            self.avatar_image = generate_avatar_image(self.avatar_bits)

            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=10
                )
            except (
                ConnectionRefusedError,
                socket.gaierror,
                OSError,
                asyncio.TimeoutError,
            ):
                print("Connection Failed {e}")
                return False

            self._reader_task = asyncio.create_task(self._listen_for_messages())
            self.connected = True
            print("Connected to server")
            resp = await self.send_command(f"name|{username}")
            if resp:
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
            self.group_observers = ClientObserverList()

    async def add_group(self, activity: GroupActivity) -> bool:
        async with self._state_lock:
            resp = await self.send_command(f"add_group|{activity.value}")
            if not resp:
                return False

            # if we get here, the first line of the response will be
            # the group info, then observers in the group

            self.current_group = ClientGroup.deserialize(resp.payload[0])

            # populate observers
            self.group_observers = ClientObserverList.from_list(
                list(ClientObserver.deserialize(x) for x in resp.payload[1:])
            )

            print(self.group_observers)

            return True

    async def join_group(self, group_name) -> bool:
        async with self._state_lock:
            resp = await self.send_command(f"join|{group_name}")
            if not resp:
                return False

            # if we get here, the first line of the response will be
            # the group info, then observers in the group

            self.current_group = ClientGroup.deserialize(resp.payload[0])

            # populate observers
            self.group_observers = ClientObserverList.from_list(
                list(ClientObserver.deserialize(x) for x in resp.payload[1:])
            )
            print(self.group_observers)

            return True

    async def leave_group(self) -> bool:
        async with self._state_lock:
            resp = await self.send_command("leave")
            if not resp:
                return False

            self.current_group = None
            self.group_observers = ClientObserverList()
            return True

    async def list_groups(self) -> list[ClientGroup]:
        resp = await self.send_command("groups")
        if not resp:
            return []

        return [ClientGroup.deserialize(x) for x in resp.payload]

    async def sync_observers(self) -> bool:
        """
        Refresh internal list of observers from
        server
        """
        if not self.current_group:
            return True

        resp = await self.send_command(f"observers|{self.current_group.name}")
        if not resp:
            self.group_observers = ClientObserverList()
            return False

        self.group_observers = ClientObserverList.from_list(
            list([ClientObserver.deserialize(x) for x in resp.payload])
        )
        return True

    async def update_pos(self, ra: float, dec: float):
        await self.send_event(EventType.POSITION, [Position(ra, dec).serialize()])

    async def send_mark(self, ra: float, dec: float, object_id: int, name: str):
        await self.send_event(
            EventType.MARK,
            [Position(ra, dec).serialize(), str(object_id), name, str(self.username)],
        )

    async def _listen_for_messages(self) -> None:
        assert self.reader is not None

        current_response_lines: list[str] = []
        current_future: Union[asyncio.Future[CommandResponse], None] = None

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
                        current_future.set_result(
                            CommandResponse(
                                status="ack", payload=current_response_lines
                            )
                        )
                        current_response_lines = []
                        current_future = None
                    elif line == "err":
                        current_future.set_result(CommandResponse("err", []))
                        current_response_lines = []
                        current_future = None
                    else:
                        current_response_lines.append(line)
                else:
                    asyncio.create_task(self._handle_event(line))

        except Exception as e:
            print(f"Reader error: {e}")
            # Optionally set exception on any pending future
            if current_future and not current_future.done():
                current_future.set_exception(e)

    async def _handle_event(self, message: str):
        print(f"[Event] {message}")
        event_parts = message.split("|")
        if len(event_parts) < 2:
            return

        try:
            event_type = EventType(event_parts[0])
        except ValueError:
            # unknown event
            return

        event = ClientEvent(event_type=event_type, payload=tuple(event_parts[1:]))

        if event.event_type == EventType.POSITION:
            if len(event.payload) != 3:
                return
            observer_name = event.payload[0]
            try:
                ra = float(event.payload[1])
                dec = float(event.payload[2])
            except ValueError:
                # bad float
                return

            self.group_observers.update_pos(observer_name, ra, dec)

        if event.event_type in [EventType.JOIN, EventType.LEAVE]:
            if len(event.payload) != 1:
                return
            observer_name = event.payload[0]
            self.publish_event(event)
            await self.sync_observers()

    async def send_event(self, event_type: EventType, payload: list[str]):
        if not self.writer:
            raise RuntimeError("Client not connected")

        event_string = f"{event_type.value}|{'|'.join(payload)}"
        self.writer.write((event_string + "\n").encode())
        await self.writer.drain()

    async def send_command(self, cmd: str, timeout: float = 5.0) -> CommandResponse:
        if not self.writer:
            raise RuntimeError("Client not connected")

        future: asyncio.Future[CommandResponse] = (
            asyncio.get_event_loop().create_future()
        )
        await self._pending_responses.put(future)

        self.writer.write((cmd + "\n").encode())
        await self.writer.drain()

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            # raise TimeoutError(f"No response received for command: {cmd!r}")
            print(f"No response received for command: {cmd!r}")
            return CommandResponse("err", [])
