#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Generates fake observer connections/actions
for testing
"""

import asyncio
import random
from StarParty.sp_client import SPClient
from StarParty.sp_usernames import sp_usernames
from StarParty.sps_data import GroupActivity


class SimulatedUser:
    def __init__(self, host: str = "spserver.local", port: int = 8728):
        self.client = SPClient()
        self.username = random.choice(sp_usernames)

        # Start around Lyra for easy PiFinder testing
        self.ra = random.uniform(280, 290)
        self.dec = random.uniform(30, 40)
        self.host = host
        self.port = port

    async def start(self):
        await asyncio.sleep(random.uniform(0.25, 2))
        success = await self.client.connect(self.username, self.host, self.port)
        if not success:
            print(f"[{self.username}] Failed to connect.")
            return

        await self._join_or_create_group()

        while True:
            # Wait some period for 'observing'
            await asyncio.sleep(random.uniform(5, 100))

            # Pick a random number of udpates to simulate a move
            for i in range(int(random.uniform(10, 50))):
                await self._send_pos_update()
                await asyncio.sleep(random.uniform(0.1, 0.8))

        # finally:
        #    await self.client.disconnect()

    async def _join_or_create_group(self):
        # get groups
        groups = await self.client.list_groups()
        if not groups or random.random() < 0.15:
            # create a group
            res = await self.client.add_group(random.choice(list(GroupActivity)))
            if not res:
                print(f"[{self.username}] Could not create group")
                return False

            print(f"[{self.username}] Created Group")

        else:
            my_group = random.choice(groups)
            res = await self.client.join_group(my_group.name)
            if not res:
                print(f"[{self.username}] Could not join group")
                return False

            print(f"[{self.username}] Joined group: {my_group.name}")
        return True

    async def _send_pos_update(self):
        self.ra += random.uniform(-1, 1)
        if self.ra > 360:
            self.ra = 360 - random.uniform(0, 10)
        if self.ra < 0:
            self.ra = 0 + random.uniform(0, 10)

        self.dec += random.uniform(-1, 1)
        if self.dec > 90:
            self.dec = 90 - random.uniform(0, 10)
        if self.dec < -90:
            self.dec = -90 + random.uniform(0, 10)
        await self.client.update_pos(self.ra, self.dec)


async def simulate_users(num_users: int, host: str = "spserver.local", port: int = 8728):
    users = [SimulatedUser(host, port) for _ in range(num_users)]
    await asyncio.gather(*(user.start() for user in users))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Simulate StarParty users.")
    parser.add_argument(
        "--num-users", type=int, default=10, help="Number of simulated users"
    )
    parser.add_argument("--host", type=str, default="spserver.local", help="Server host")
    parser.add_argument("--port", type=int, default=8728, help="Server port")
    args = parser.parse_args()

    asyncio.run(simulate_users(args.num_users, args.host, args.port))
