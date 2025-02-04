"""This module contains the tests for a single charger.

"""

import asyncio

import pytest
from utils import SimConnection, make_assert


@pytest.mark.asyncio(loop_scope="function")
async def test_case1():
    """A regular, single test scenario without any thrills.

    Manual start and stop.
    """

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Wait a little to ensure various initializations are done.
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable
    response = await conn.command("plugin")
    assert response == "Cable plugged. Status Preparing"

    # scan the default tag
    response = await conn.command("tag")
    assert response == "Tag Accepted. Parent: , new status: SuspendedEVSE"

    await asyncio.sleep(10)  # Charge for a little, check status
    response = await conn.command("status")
    assert (
        response
        == "Status: Charging, transaction_id: 1, offer: 6.0 A, energy (rounded): 0 Wh, delay: False, max_usage: None"
    )

    await asyncio.sleep(181)  # Charge for a little, check status
    response = await conn.command("status")
    assert (
        response
        == "Status: Charging, transaction_id: 1, offer: 9.0 A, energy (rounded): 200 Wh, delay: False, max_usage: None"
    )

    await asyncio.sleep(181)  # Charge for a little, check status
    response = await conn.command("status")
    assert (
        response
        == "Status: Charging, transaction_id: 1, offer: 12.0 A, energy (rounded): 600 Wh, delay: False, max_usage: None"
    )

    await asyncio.sleep(181)  # Charge for a little, check status
    response = await conn.command("status")
    make_assert(response)
    assert (
        response
        == "Status: Charging, transaction_id: 1, offer: 18.0 A, energy (rounded): 1100 Wh, delay: False, max_usage: None"
    )

    # Finish charging by unplugging the cable
    response = await conn.command("unplug")
    assert response == "Succesfully stopped transaction. id_tag_info: None"

    # Wait a little to close things off
    await asyncio.sleep(5)

    response = await conn.command("status")
    assert (
        response
        == "Status: Available, transaction_id: None, offer: 0.0 A, energy (rounded): 0 Wh, delay: False, max_usage: None"
    )

    # Disconnect from the simulator
    await conn.disconnect()


@pytest.mark.asyncio(loop_scope="function")
async def test_case2():
    """Manual start, stopped by call full."""

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Wait a little to ensure various initializations are done.
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable
    response = await conn.command("plugin")
    assert response == "Cable plugged. Status Preparing"

    # scan the default tag
    response = await conn.command("tag")
    assert response == "Tag Accepted. Parent: , new status: SuspendedEVSE"

    await asyncio.sleep(10)  # Charge for a little, check status
    response = await conn.command("status")
    assert (
        response
        == "Status: Charging, transaction_id: 1, offer: 6.0 A, energy (rounded): 0 Wh, delay: False, max_usage: None"
    )

    await asyncio.sleep(300)  # Let charge for 5 min.
    response = await conn.command("status")
    make_assert(response)

    # car full
    response = await conn.command("full")
    make_assert(response)

    await asyncio.sleep(65)  # wait to see offer go away
    response = await conn.command("status")
    make_assert(response)

    # unplug
    response = await conn.command("unplug")
    assert response == "Succesfully stopped transaction. id_tag_info: None"

    # Wait a little to close things off
    await asyncio.sleep(5)

    response = await conn.command("status")
    assert (
        response
        == "Status: Available, transaction_id: None, offer: 0.0 A, energy (rounded): 0 Wh, delay: False, max_usage: None"
    )

    # Disconnect from the simulator
    await conn.disconnect()


def main():
    # Run test case outside of pytest
    asyncio.run(test_case2())


if __name__ == "__main__":
    main()
