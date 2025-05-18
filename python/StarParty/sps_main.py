#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Primary module for the Star Party local server
"""

import asyncio
import uuid
from random import choice
from time import time

from StarParty.sps_data import Observer, ServerState, EventType

state_lock = asyncio.Lock()
server_state = ServerState()


def make_group_name() -> str:
    adjectives = [
        "stellar",
        "bright",
        "dark",
        "radiant",
        "cosmic",
        "galactic",
        "wispy",
        "nebular",
        "variable",
        "local",
        "infrared",
        "radio",
    ]

    nouns = [
        "nova",
        "quasar",
        "nebula",
        "comet",
        "pulsar",
        "galaxy",
        "asteroid",
        "scope",
        "dwarf",
        "cluster",
        "planet",
        "moon",
        "orbit",
        "flare",
        "core",
    ]

    adj = choice(adjectives)
    noun = choice(nouns)
    return f"{adj.capitalize()}{noun.capitalize()}"


async def writeline(writer: asyncio.StreamWriter, message: str):
    message = message + "\n"
    writer.write(message.encode())
    await writer.drain()


async def handle_command(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, observer: Observer
):
    global server_state

    connection_id = observer.connection_id
    connection_id_short = connection_id[-4:]

    while True:
        in_data_raw = await reader.readline()
        try:
            in_data = in_data_raw.decode().strip()
        except UnicodeDecodeError:
            in_data = "error"

        if in_data == "":
            # This indicates EOF/Reader closed
            break

        print(f"{connection_id_short}:{in_data}")
        command = in_data.split("|")
        if command[0] == "echo":  # echo
            await writeline(writer, command[1])

        elif command[0] == "pos":  # set position
            async with state_lock:
                observer.position.ra = float(command[1])
                observer.position.dec = float(command[2])
                if observer.group is not None:
                    observer.group.add_event(
                        EventType.POSITION,
                        (observer, float(command[1]), float(command[2])),
                    )

        elif command[0] == "groups":  # list groups
            for group_touple in server_state.list_groups():
                await writeline(writer, f"{group_touple[0]}|{group_touple[1]}")
            await writeline(writer, "ack")

        elif command[0] == "observers":  # list observers with groups
            for observer_touple in server_state.list_observers():
                await writeline(writer, f"{observer_touple[0]}|{observer_touple[1]}")
            await writeline(writer, "ack")

        elif command[0] == "add_group":  # Add new group
            new_group_name = make_group_name()
            async with state_lock:
                new_group = server_state.add_group(observer, new_group_name)
            await writeline(writer, new_group.name)

        elif command[0] == "join":  # join group
            group_name = command[1]
            async with state_lock:
                result = server_state.join_group(observer, group_name)

            if result:
                await writeline(writer, "ack")
            else:
                await writeline(writer, "err")
        elif command[0] == "leave":  # leave current group
            async with state_lock:
                result = server_state.leave_group(observer)

            if result:
                await writeline(writer, "ack")
            else:
                await writeline(writer, "err")
        else:
            # unknown command
            await writeline(writer, "err")


async def send_event_updates(writer: asyncio.StreamWriter, observer: Observer):
    global server_state
    last_event_time: float = 0
    while True:
        if observer.group is not None and last_event_time > 0:
            if event := observer.group.get_next_event(last_event_time):
                try:
                    await writeline(writer, event.serialize())
                except ConnectionResetError:
                    # Tried to write, but lost connection
                    break
                last_event_time = event.event_time
        else:
            # if they are not a member of a group right now
            # update the last event time so they only get events
            # since they joined
            last_event_time = time()

        await asyncio.sleep(0.1)


async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global server_state

    connection_id = str(uuid.uuid4())
    connection_id_short = connection_id[-4:]
    print(f"{connection_id_short}: Attempt")
    in_data_raw = await reader.readline()
    in_data = in_data_raw.decode()
    command = in_data.split("|")
    if len(command) != 2 or command[0] != "name":
        await writeline(writer, "err")
        print(f"{connection_id_short}: Bad Connection Attempt")
        writer.close()
        await writer.wait_closed()
        return

    # Register new connection
    observer_name = command[1].strip()
    observer = Observer(
        connection_id=connection_id,
        name=observer_name,
        group=None,
    )
    async with state_lock:
        server_state.observers.append(observer)

    await writeline(writer, "ack")
    print(f"{connection_id_short}: {observer_name} Connected")
    await asyncio.gather(
        handle_command(reader, writer, observer), send_event_updates(writer, observer)
    )
    print(f"{connection_id_short}: Closed")


async def server_main(host: str, port: int):
    sp_srv = await asyncio.start_server(client_connected, port=port)
    print("Starting Server....")
    async with sp_srv:
        await sp_srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(server_main("127.0.0.1", 8728))
