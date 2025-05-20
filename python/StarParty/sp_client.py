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
from StarParty.sps_data import Position


@dataclass
class ClientObserver:
    name: str
    group: Union[str, None] = None
    position: Position = field(default_factory=Position)

    def __str__(self):
        return self.name


class SPClient:
    def __init__(self):
        self.reader: Union[StreamReader, None] = None
        self.writer: Union[StreamWriter, None] = None
        self._observers: list[ClientObserver] = []
        self.connected: bool = False
        self.username: Union[str, None] = None

        self._reader_task: Union[asyncio.Task, None] = None

    async def connect(self, host: str, port: int, username: str):
        # Create A queue of Futures for awaiting responses and a lock
        self._pending_responses: asyncio.Queue[asyncio.Future[str]] = asyncio.Queue()
        self._state_lock = asyncio.Lock()

        self.username = username
        self.reader, self.writer = await asyncio.open_connection(host, port)
        self._reader_task = asyncio.create_task(self._listen_for_messages())
        self.connected = True
        print("Connected to server")
        resp = await self.send_command(f"name|{username}")
        print(resp)

    async def disconnect(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self.connected = False

    async def _listen_for_messages(self):
        assert self.reader is not None
        current_response_lines: list[str] = []
        current_future: Union[asyncio.Future[str], None] = None

        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    print("Server closed connection")
                    break

                line = line.decode().rstrip("\n")

                if line.startswith("\t"):
                    # strip tab
                    line = line[1:]
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
        # async with self._state_lock:
        #    self._state["last_event"] = message

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
