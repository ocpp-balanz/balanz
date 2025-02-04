"""test utility functions"""

import asyncio

import websockets


class SimConnection:
    """Simulator connection class."""

    def __init__(self, url: str):
        self.url = url
        self.ws = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.url)
        await asyncio.sleep(1)
        print(f"Connected to {self.url}")

    async def disconnect(self) -> None:
        if self.ws is not None:
            await self.ws.close()
            print("Disconnected from simulator")

    async def command(self, command: str) -> str:
        if self.ws is not None:
            await self.ws.send(command)
            response = await self.ws.recv()
            return response
        else:
            return "Not connected"


def make_assert(response):
    print(f'    assert(response == "{response}")')
