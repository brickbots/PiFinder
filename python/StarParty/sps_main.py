#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Primary module for the Star Party local server
"""

import asyncio
import uuid
import contextlib
from random import choice
from time import time

from StarParty.sps_data import Observer, ServerState, EventType, GroupActivity

state_lock = asyncio.Lock()
server_state = ServerState()


def make_group_name(current_names: list[str]) -> str:
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
        "compact",
        "spiral",
        "diffuse",
        "dwarf",
        "double",
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
        "cluster",
        "planet",
        "moon",
        "orbit",
        "flare",
        "core",
        "group",
        "star",
        "system",
        "arm",
    ]

    return_name = None
    while return_name is None:
        adj = choice(adjectives)
        noun = choice(nouns)
        return_name = f"{adj.capitalize()}{noun.capitalize()}"
        if return_name in current_names:
            return_name = None
    return return_name


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
        if not in_data_raw:
            print(f"{connection_id_short}: Closed in reader")
            return

        try:
            in_data = in_data_raw.decode().strip()
        except UnicodeDecodeError:
            in_data = "error"

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
            for group_string in server_state.list_groups():
                await writeline(writer, f"\t{group_string}")
            await writeline(writer, "\tack")

        elif command[0] == "observers":  # list observers with groups
            for observer_string in server_state.list_observers():
                await writeline(writer, f"\t{observer_string}")
            await writeline(writer, "\tack")

        elif command[0] == "add_group":  # Add new group
            new_group_name = make_group_name([x[0] for x in server_state.list_groups()])
            try:
                new_activity = GroupActivity(command[1])
            except ValueError:
                await writeline(writer, "\terr")
                return

            async with state_lock:
                new_group = server_state.add_group(
                    observer, new_group_name, new_activity
                )
            await writeline(writer, f"\t{new_group.name}\n\tack")

        elif command[0] == "join":  # join group
            group_name = command[1]
            async with state_lock:
                result_group = server_state.join_group(observer, group_name)

            if result_group:
                # write group info
                await writeline(
                    writer, f"\t{result_group.name}|{result_group.activity.value}"
                )

                # write out observers in the group
                for observer in result_group.observers:
                    await writeline(writer, f"\t{observer.serialize()}")

                await writeline(writer, "\tack")
            else:
                await writeline(writer, "\terr")
        elif command[0] == "leave":  # leave current group
            async with state_lock:
                result = server_state.leave_group(observer)

            if result:
                await writeline(writer, "\tack")
            else:
                await writeline(writer, "\terr")
        else:
            # unknown command
            await writeline(writer, "\terr")


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

        await asyncio.sleep(0.025)


async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global server_state

    connection_id = str(uuid.uuid4())
    connection_id_short = connection_id[-4:]
    print(f"{connection_id_short}: Attempt")

    try:
        in_data_raw = await asyncio.wait_for(reader.readline(), timeout=5)
        if not in_data_raw:
            # client disconnected before sending
            print(f"{connection_id_short}: Disconnected before name")
            writer.close()
            await writer.wait_closed()
            return
    except asyncio.TimeoutError:
        print(f"{connection_id_short}: Timeout")
        writer.close()
        await writer.wait_closed()
        return

    in_data = in_data_raw.decode()
    command = in_data.split("|")
    if len(command) != 2 or command[0] != "name":
        await writeline(writer, "\terr")
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

    await writeline(writer, "\tack")
    print(f"{connection_id_short}: {observer_name} Connected")

    command_task = asyncio.create_task(handle_command(reader, writer, observer))
    event_task = asyncio.create_task(send_event_updates(writer, observer))

    try:
        done, _pending = await asyncio.wait(
            [command_task, event_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if (e := task.exception()) is not None:
                raise e

    except Exception as e:
        print(f"{connection_id_short}: {e}")

    finally:
        for task in (command_task, event_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    writer.close()
    await writer.wait_closed()

    # Cleanup connection here....
    async with state_lock:
        server_state.remove_observer(observer)
    print(f"{connection_id_short}: Closed")


async def server_main(host: str, port: int):
    sp_srv = await asyncio.start_server(client_connected, port=port)
    print("Starting Server....")
    async with sp_srv:
        await sp_srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(server_main("127.0.0.1", 8728))
