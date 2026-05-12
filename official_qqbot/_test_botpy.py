"""Test with official qq-botpy SDK"""

import asyncio

asyncio.set_event_loop(asyncio.new_event_loop())

import botpy
from botpy.message import GroupMessage


class MyClient(botpy.Client):
    async def on_ready(self):
        print(f"[READY] Bot is ready!")

    async def on_group_at_message_create(self, message: GroupMessage):
        print(f"[GROUP MSG] {message.content}")


intents = botpy.Intents(public_messages=True)
client = MyClient(intents=intents, is_sandbox=False)
client.run(appid="1903707124", secret="QAvgSE1ocRG6wneWOHA4ytplifdbaZZZ")
