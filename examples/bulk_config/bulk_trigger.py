import json
import random
import asyncio
import websockets
from ocpp.messages import MessageType
import argparse
import sys

# Python example for how to bulk trigger notifications (status, boot or meter) across a set of chargers.

# The set of chargers can be scoped either by group, but the inverse of a group; or all chargers.

# Note the required dependencies, which may be either installed via pip or using the Makefile
# install command in the root of the project

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

async def bulk(args):
    # Connect to balanz API.
    client = BalanzConnection(args.url)
    await client.connect()
    ok, response = await client.command("Login", {"token": args.user + args.password})
    if ok != MessageType.CallResult:
        print("Login failed", response)
        return
    print("Succesfully logged in")

    # Ok, lets get a list of all chargers and their groups so we can filter.
    ok, response = await client.command("GetChargers", {})
    if ok != MessageType.CallResult:
        print("Failed to get chargers", response)
        return
    
    charger_list = []
    for charger in response:
        if not args.group_id or (charger["group_id"] == args.group_id and not args.invert) or \
            (charger["group_id"] != args.group_id and args.invert):
            charger_list.append(charger["charger_id"])

    if len(charger_list) == 0:
        print("No chargers scoped, exiting")
        return

    print("Chargers scoped:", charger_list)
    for charger_id in charger_list:
        print("Triggering for", charger_id)
        # {"charger_id": "charger_id", "requested_message": "MeterValues", "connector_id": 1}
        ok, response = await client.command("TriggerMessage", {"charger_id": charger_id, "requested_message": args.notification, "connector_id": 1})
        if ok != MessageType.CallResult:
            print("  Failed to trigger notifcation", response)
        else:
            print("  Triggered notification succesfully")

    # Disconnect from balanz API.
    await client.disconnect()

def main():
    # Argument stuff.
    parser = argparse.ArgumentParser(description="bulk script for triggering notifications via balanz",
                                     epilog="Example: python bulk_trigger.py --user I_Am_Random --password 27 --group_id HQ")
    parser.add_argument(
        "--url",
        type=str,
        default="ws://localhost:9999/api",
        help="URL for balanz API",
    )
    parser.add_argument(
        "--user",
        type=str,
        help="The user to connect as",
    )
    parser.add_argument(
        "--password",
        type=str,
        help="The password for the user",
    )
    parser.add_argument(
        "--notification",
        default="BootNotification",
        type=str,
        help="The type of notification to trigger. Options are BootNotification, StatusNotification, MeterValues",
    )
    parser.add_argument(
        "--group_id",
        type=str,
        help="The group of which to target all chargers. Omit to target all."
    )
    parser.add_argument(
        "--invert",
        type=bool, 
        default=False, 
        help="Invert the group selection, i.e. select all chargers NOT in that group"
    )

    args = parser.parse_args()
    if not args.user or not args.password:
        parser.print_help()
        sys.exit(1)


    asyncio.run(bulk(args))

if __name__ == "__main__":
    main()
