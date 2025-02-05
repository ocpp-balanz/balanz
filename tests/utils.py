"""test utility functions"""

import asyncio
from inspect import getframeinfo, stack

import websockets

PASS_TESTS = False


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


def check(response: str, target: str) -> bool:
    """pytest assertation helper which can be used to build results."""
    global PASS_TESTS

    if PASS_TESTS:
        caller = getframeinfo(stack()[1][0])
        print(f"TEST - {caller.filename}:{caller.lineno}")
        print("Response: ", response)
        print("Target  : ", target)
        print("Passed  : ", response == target)
        if response != target:
            print(f"Update assertion in line {caller.lineno} to:")
            print(f'    assert check(response, "{response}")')
        print("")
        return True
    else:
        return response == target


def set_pass_tests(pass_tests: bool) -> None:
    global PASS_TESTS

    PASS_TESTS = pass_tests
