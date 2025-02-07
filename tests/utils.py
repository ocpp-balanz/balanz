"""test utility functions"""

import asyncio
import json
import random
from inspect import getframeinfo, stack

import websockets
from ocpp.messages import MessageType

PASS_TESTS = False
TEST_TOKEN = "I_Am_Random27"


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
            print("Disconnected")

    async def command(self, command: str) -> str:
        if self.ws is not None:
            await self.ws.send(command)
            response = await self.ws.recv()
            return response
        else:
            return "Not connected"


def prune(obj, keys: list[str], exclude: bool = False):
    """prunes a structure. If the structure contains dict objects, only retain attributes (on any level)
    matching the specified keys. If exclude set, retains all BUT those."""
    if isinstance(obj, dict):
        return {
            k: prune(obj=obj[k], keys=keys)
            for k in obj.keys()
            if (not exclude and k in keys) or (exclude and k not in keys)
        }
    elif isinstance(obj, list):
        return [prune(obj=i, keys=keys) for i in obj]
    else:
        return obj


def prune_chargers(chargers, keys: list[str] = None):
    """Prunes a list of chargers to fields of primary interest for testing

    keys may be supplied if fewer/other keys are requested."""
    if keys is None:
        keys = [
            "connectors",
            "1",
            "transaction",
            "charger_id",
            "alias",
            "offer",
            "transaction_id",
            "status",
            "priority",
            "id_tag",
            "meter_start",
            "user_name",
            "usage_meter",
            "energy_meter",
        ]
    return [prune(c, keys=keys) for c in chargers]


def check_chargers(response, target):
    prune_response = prune_chargers(response)
    prune_response_no_energy = prune(prune_response, keys="energy_meter", exclude=True)
    target_no_energy = prune(target, keys="energy_meter", exclude=True)
    ok = str(prune_response_no_energy) == str(target_no_energy)
    # TODO: Compare energy_meter values (with some tolerance..)

    global PASS_TESTS

    if PASS_TESTS:
        caller = getframeinfo(stack()[1][0])
        print(f"TEST - {caller.filename}:{caller.lineno}")
        print("Response: ", prune_response)
        print("Passed  : ", ok)
        if not ok:
            print("Target  : ", target)
            print(f"Update assertion in line {caller.lineno} to:")
            print(f"    assert check_chargers(response, {prune_response})")
        print("")
        return True
    else:
        return ok


class BalanzConnection:
    """Balanz connection class"""

    def __init__(self, url: str):
        self.url = url
        self.ws = None

    @staticmethod
    def message_id() -> str:
        return str(random.randint(10000, 99999))

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.url, subprotocols=["ocpp1.6"])
        await asyncio.sleep(1)
        print(f"Connected to {self.url}")

    async def disconnect(self) -> None:
        if self.ws is not None:
            await self.ws.close()
            print("Disconnected")

    async def command(self, command: str, payload) -> tuple[int, str]:
        """Command/Reply (or Error) exchange"""
        if self.ws is not None:
            # Build the command with a random message id.
            call = json.dumps([MessageType.Call, self.message_id(), command, payload])
            await self.ws.send(call)
            response = json.loads(await self.ws.recv())
            return response[0], response[2]
        else:
            return MessageType.CallError, "Not connected"


def check(response: str, target: str) -> bool:
    """pytest assertation helper which can be used to build results."""
    global PASS_TESTS

    # Small hack. When comparing "Status: ..." responses with energy values, even
    # if the simulator rounds them (maybe it should not)
    if response.startswith("Status: ") and " Wh, " in response and " Wh, " in target:
        # The Energy values will be just before "Wh"
        rs = response.split()
        ri = rs.index("Wh,")
        renergy = int(rs[ri - 1])
        ts = target.split()
        ti = ts.index("Wh,")
        tenergy = int(ts[ti - 1])
        ok = abs(renergy - tenergy) <= 300 and rs[0 : ri - 1] == ts[0 : ti - 1] and rs[ri:] == ts[ti:]
    else:
        ok = response == target

    if PASS_TESTS:
        caller = getframeinfo(stack()[1][0])
        print(f"TEST - {caller.filename}:{caller.lineno}")
        print("Response: ", response)
        print("Passed  : ", ok)
        print("Target  : ", target)
        if not ok:
            print(f"Update assertion in line {caller.lineno} to:")
            print(f'    assert check(response, "{response}")')
        print("")
        return True
    else:
        return ok


def set_pass_tests(pass_tests: bool) -> None:
    global PASS_TESTS

    PASS_TESTS = pass_tests
