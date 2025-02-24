"""This module contains the tests for a single charger.
"""

import asyncio

import pytest
from utils import SimConnection, check, set_pass_tests

# Uncomment below to enable test passing and automatic assert statement creation.
# May also require to comment out below pytest.fixture statement to make it run.
set_pass_tests(True)


@pytest.mark.asyncio(loop_scope="module")
async def test_case1():
    """Simple delay case - charging does not start."""

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Ensure things are initialized, even if simulator not restarted
    await conn.command("unplug")
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable, set delay state
    response = await conn.command("delay")
    response = await conn.command("delay_trans")
    response = await conn.command("plugin")
    assert check(response, "Cable plugged. Status Preparing")

    # scan the default tag
    response = await conn.command("tag")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait a little, review that stays in SuspendedEV state, but that transaction has started.
    await asyncio.sleep(30)
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEV, transaction_id: 1, offer: 6.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    await asyncio.sleep(400)  # Wait 5+ min, then offer should have been taken back
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEVSE, transaction_id: 1, offer: 0.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    # Finish charging by unplugging the cable
    response = await conn.command("unplug")
    assert check(response, "Succesfully stopped transaction. id_tag_info: None")


@pytest.mark.asyncio(loop_scope="module")
async def test_case2():
    """Simple delay case - charging starts during 5 min wait ."""

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Ensure things are initialized, even if simulator not restarted
    await conn.command("unplug")
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable, set delay state
    response = await conn.command("delay")
    response = await conn.command("delay_trans")
    response = await conn.command("plugin")
    assert check(response, "Cable plugged. Status Preparing")

    # scan the default tag
    response = await conn.command("tag")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait a little, review that stays in SuspendedEV state, but that transaction has started.
    await asyncio.sleep(100)
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEV, transaction_id: 1, offer: 6.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    # Now allow charing
    response = await conn.command("nodelay")
    response = await conn.command("resume")
    await asyncio.sleep(30)  # Wait a litte, charging should have started.
    response = await conn.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 6.0 A, energy: 200 Wh, delay: False, max_usage: None",
    )

    # Finish charging by unplugging the cable
    response = await conn.command("unplug")
    assert check(response, "Succesfully stopped transaction. id_tag_info: None")

    # Wait a little to close things off
    await asyncio.sleep(5)

    response = await conn.command("status")
    assert check(
        response,
        "Status: Available, transaction_id: None, offer: 0.0 A, energy: 0 Wh, delay: False, max_usage: None",
    )

    # Disconnect from the simulator
    await conn.disconnect()


@pytest.mark.asyncio(loop_scope="module")
async def test_case3():
    """Simple delay case - charging does not start W/O creating transaction"""

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Ensure things are initialized, even if simulator not restarted
    await conn.command("unplug")
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable, set delay state
    response = await conn.command("delay")
    response = await conn.command("delay_notrans")
    response = await conn.command("plugin")
    assert check(response, "Cable plugged. Status Preparing")

    # scan the default tag
    response = await conn.command("tag")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait a little, review that stays in SuspendedEV state, but that transaction has started.
    await asyncio.sleep(130)
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEV, transaction_id: None, offer: 6.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    await asyncio.sleep(400)  # Wait 5+ min, then offer should have been taken back
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEVSE, transaction_id: None, offer: 0.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    # Finish charging by unplugging the cable
    await asyncio.sleep(10)
    response = await conn.command("unplug")
    assert check(response, "Ok, status change to available")


@pytest.mark.asyncio(loop_scope="module")
async def test_case4():
    """Simple delay case - charging starts during 5 min wait W/O first doing transaction ."""

    url = "ws://localhost:1234"

    # Create a connection to the simulator
    conn = SimConnection(url)
    await conn.connect()
    if not conn.ws:
        raise Exception(f"Failed to connect to simulator at {url}")

    # Ensure things are initialized, even if simulator not restarted
    await conn.command("unplug")
    await asyncio.sleep(5)

    # Standard charging scenario
    # plugin cable, set delay state
    response = await conn.command("delay")
    response = await conn.command("delay_notrans")
    response = await conn.command("plugin")
    assert check(response, "Cable plugged. Status Preparing")

    # scan the default tag
    response = await conn.command("tag")

    # Wait a little, review that stays in SuspendedEV state, but that transaction has started.
    await asyncio.sleep(100)
    response = await conn.command("status")
    assert check(
        response,
        "Status: SuspendedEV, transaction_id: None, offer: 6.0 A, energy: 0 Wh, delay: True, max_usage: None",
    )

    # Now allow charing
    response = await conn.command("delay_trans")
    response = await conn.command("nodelay")
    await asyncio.sleep(90)  # Wait a litte, charging should have started.
    response = await conn.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: None, offer: 6.0 A, energy: 200 Wh, delay: False, max_usage: None",
    )

    # Finish charging by unplugging the cable
    response = await conn.command("unplug")
    assert check(response, "Ok, status change to available")

    # Wait a little to close things off
    await asyncio.sleep(100)

    response = await conn.command("status")
    assert check(
        response,
        "Status: Available, transaction_id: None, offer: 0.0 A, energy: 0 Wh, delay: False, max_usage: None",
    )

    # Disconnect from the simulator
    await conn.disconnect()


def main():
    # Run test case outside of pytest
    asyncio.run(test_case1())
    asyncio.run(test_case2())
    asyncio.run(test_case3())
    asyncio.run(test_case4())


if __name__ == "__main__":
    main()
