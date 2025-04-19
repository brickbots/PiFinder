#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Primary module for the Star Party local server
"""

import asyncio
import uuid
from random import random

from SPServer.sps_data import Observer, ServerState, Mark, Group, Position

state_lock = asyncio.Lock()
server_state = ServerState()


async def handle_command(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, observer: Observer):
    global server_state

    connection_id = observer.connection_id
    connection_id_short = connection_id[-4]

    while True:
        in_data_raw = await reader.readline()
        in_data = in_data_raw.decode()
        if in_data == "":
            # This indicates EOF/Reader closed
            break

        print(f"{connection_id_short}:{in_data}")
        command = in_data.split("|")
        if command[0] == "echo":  # echo
            writer.write(command[1].encode())
            await writer.drain()

        if command[0] == "pos":  # set position
            with state_lock:
                observer.position.ra=float(command[1])
                observer.position.dec=float(command[2])

        if command[0] == "groups": # list groups
            


async def send_pos_updates(writer: asyncio.StreamWriter, observer: Observer):

    global server_state
    while True:
        if random() > 0.9:
            writer.write("pos|20|20\n".encode())
            try:
                await writer.drain()
            except ConnectionResetError:
                # Tried to write, but lost connection
                break
        await asyncio.sleep(0.1)


async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global server_state

    connection_id = str(uuid.uuid4())
    connection_id_short = connection_id[-4]
    print(f"{connection_id_short}: Attempt")
    in_data_raw = await reader.readline()
    in_data = in_data_raw.decode()
    command = in_data.split("|")
    if len(command) != 2 or command[0] != "name":
        print(f"{connection_id_short}: Bad Connection Attempt")
        writer.close()
        await writer.wait_closed()
        return

    # Register new connection
    observer_name = command[1]
    observer = Observer(
        connection_id=connection_id,
        name=observer_name,
        group=None,
    )
    with state_lock:
        server_state.observers.append(observer)

    print(f"{connection_id_short}: {observer_name} Connected")
    await asyncio.gather(handle_command(reader, writer, observer), send_pos_updates(writer, observer))
    print(f"{connection_id_short}: Closed")


async def server_main(host: str, port: int):
    sp_srv = await asyncio.start_server(client_connected, port=port)
    print("Starting Server....")
    async with sp_srv:
        await sp_srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(server_main("127.0.0.1", 8728))
