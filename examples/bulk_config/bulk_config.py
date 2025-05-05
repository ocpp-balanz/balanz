import json
import random
import asyncio
import websockets
from ocpp.messages import MessageType
import argparse
import sys

# Python example for how to bulk update (w/ initial check to not update if already set correctly)
# a configuration setting across a set of chargers.

# The set of chargers can be scoped either by charger_id or by an entire group; or all chargers.

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
        print("Checking", charger_id)
        # {"charger_id": "TACW223437G682", "key": ["LocalAuthorizeOffline"]}
        ok, response = await client.command("GetConfiguration", {"charger_id": charger_id, "key": [args.key]})
        if ok != MessageType.CallResult:
            print("  Failed to get configuration", response)
            continue

        values = response["configuration_key"]
        found_value = False
        for v in values:
            if v["key"] == args.key:
                value = str(v["value"])
                found_value = True

                if value == args.value:
                    print("    value already ok - no change required. value is:", value)
                else:
                    print("    value mismatch. Value is", value, "and should be", args.value)

                    if args.update:
                        ok, response = await client.command("ChangeConfiguration", {"charger_id": charger_id, "key": args.key, "value": args.value})
                        if ok != MessageType.CallResult:
                            print("  failed to set configuration", response)
                        else:
                            print("  succesfully updated confiuration")
        if not found_value:
            print("  value not found")

    # Disconnect from balanz API.
    await client.disconnect()




def main():
    # Argument stuff.
    parser = argparse.ArgumentParser(description="bulk script for changing charger config via balanz",
                                     epilog="Example: python bulk_config.py --user I_Am_Random --password 27 --key LocalAuthorizeOffline --value FALSE --group_id HQ --invert true ")
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
        "--key",
        type=str,
        help="The key to change",
    )
    parser.add_argument(
        "--value",
        type=str,
        help="The value to set/ensure",
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
    parser.add_argument(
        "--update",
        type=bool,
        default=False,
        help="Update the configuration value. Default is to only check if it is set correctly"
    )

    args = parser.parse_args()
    if not args.user or not args.password or not args.key or not args.value:
        parser.print_help()
        sys.exit(1)


    asyncio.run(bulk(args))

if __name__ == "__main__":
    main()
