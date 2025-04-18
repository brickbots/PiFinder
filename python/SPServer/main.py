#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Primary module for the Star Party local server
"""

import asyncio
from random import random

test_dict = {}


async def handle_command(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global test_dict
    while True:
        in_data_raw = await reader.readline()
        in_data = in_data_raw.decode()
        if in_data == "":
            # This indicates EOF/Reader closed
            break

        print("in: " + in_data)
        command = in_data.split("|")
        if command[0] == "e":  # echo
            writer.write(command[1].encode())
            await writer.drain()

        if command[0] == "s":  # set
            # lock
            # update
            pass


async def update_pos(writer: asyncio.StreamWriter):
    global test_dict
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
    print("Client connected")
    await asyncio.gather(handle_command(reader, writer), update_pos(writer))
    print("Client CLOSED")


async def server_main(host: str, port: int):
    sp_srv = await asyncio.start_server(client_connected, port=port)
    print("Starting Server....")
    async with sp_srv:
        await sp_srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(server_main("127.0.0.1", 8728))
