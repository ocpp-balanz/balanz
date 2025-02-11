"""This module contains the tests for multiple chargers, balancing the load.
"""

import asyncio

import pytest
from utils import TEST_TOKEN, BalanzConnection, SimConnection, check, check_chargers, set_pass_tests

# Uncomment below to enable test passing and automatic assert statement creation.
set_pass_tests(True)


# @pytest.fixture(scope="module")
@pytest.mark.asyncio(loop_scope="function")
async def test_case1():
    """balanz'ing scenarios using RR2 chargers."""

    # Setup connections to simulators. Name by their alias
    # Charger        | Charger Alias | Websocket port for command interface
    # ---------------|---------------|----------------------
    # TACW224317G584 | RR2-01        | 1235
    # TACW224137G670 | RR2-02        | 1236
    # TACW224537G682 | RR2-03        | 1237
    # TACW223437G682 | RR2-04        | 1238

    # Recall the group setup. Only RR2-01 is in RR2-HIGH, rest in RR2-LOW
    # RR2,ACME,Road Runner 2 Site,,00:00-23:59>0=24:3=40:5=48
    # RR2-LOW,RR2,Road Runner 2 Site low priority,1,
    # RR2-HIGH,RR2,Road Runner 2 Site low priority,3,

    # Connect to balanz API
    bz_conn = BalanzConnection("ws://localhost:9999/api")
    await bz_conn.connect()
    await bz_conn.command("Login", {"token": TEST_TOKEN})

    rr2_01 = SimConnection("ws://localhost:1235")
    await rr2_01.connect()
    rr2_02 = SimConnection("ws://localhost:1236")
    await rr2_02.connect()
    rr2_03 = SimConnection("ws://localhost:1237")
    await rr2_03.connect()
    rr2_04 = SimConnection("ws://localhost:1238")
    await rr2_04.connect()

    # Ensure things are initialized, even if simulator not restarted
    connections = [rr2_01, rr2_02, rr2_03, rr2_04]
    for conn in connections:
        await conn.command("unplug")
    await asyncio.sleep(5)

    # Agree on starting point from balanz point of view
    _, response = await bz_conn.command("GetChargers", {"group_id": "RR2"})
    assert check_chargers(
        response,
        [
            {
                "charger_id": "TACW224137G670",
                "alias": "RR2-02",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW224537G682",
                "alias": "RR2-03",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW223437G682",
                "alias": "RR2-04",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW224317G584",
                "alias": "RR2-01",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 3}},
            },
        ],
    )

    # Standard charging scenario
    # plugin cables
    for conn in connections:
        response = await conn.command("plugin")
        assert check(response, "Cable plugged. Status Preparing")
    await asyncio.sleep(5)

    # scan a low priority tag (1) on a low priority charger (rr2_04) which has 8A limit
    response = await rr2_04.command("tag E08CEE18")
    assert check(response, "Tag Accepted. Parent: ACME, new status: SuspendedEVSE")

    await asyncio.sleep(20)  # Charge for a little, check status
    response = await rr2_04.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 6.0 A, energy: 100 Wh, delay: False, max_usage: None",
    )

    _, response = await bz_conn.command("GetChargers", {"group_id": "RR2"})
    assert check_chargers(
        response,
        [
            {
                "charger_id": "TACW224137G670",
                "alias": "RR2-02",
                "connectors": {"1": {"transaction_id": None, "status": "Preparing", "priority": 1}},
            },
            {
                "charger_id": "TACW224537G682",
                "alias": "RR2-03",
                "connectors": {"1": {"transaction_id": None, "status": "Preparing", "priority": 1}},
            },
            {
                "charger_id": "TACW223437G682",
                "alias": "RR2-04",
                "connectors": {
                    "1": {
                        "transaction_id": 1,
                        "status": "Charging",
                        "priority": 1,
                        "transaction": {
                            "id_tag": "E08CEE18",
                            "start_time": 1738942607.755792,
                            "meter_start": 0,
                            "user_name": "Corp EV 2",
                            "usage_meter": 5.95,
                            "energy_meter": 136.0,
                        },
                    }
                },
            },
            {
                "charger_id": "TACW224317G584",
                "alias": "RR2-01",
                "connectors": {"1": {"transaction_id": None, "status": "Preparing", "priority": 3}},
            },
        ],
    )

    await asyncio.sleep(300)  # Charge for a little, check status. Should land at 8A.
    response = await rr2_04.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 8.0 A, energy: 500 Wh, delay: False, max_usage: None",
    )

    # rr2_03 has 16A limit. However, 8A will stay at rr2_04
    # Tagging with a non priority tag, so will end up with priority
    response = await rr2_03.command("tag 56EB8FBF")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait (a long time!) and check
    await asyncio.sleep(1000)
    response = await rr2_03.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 16.0 A, energy: 2500 Wh, delay: False, max_usage: None",
    )

    # Enter, next player. High priority rr2_01. Set the max to 16 and let it do it's things
    response = await rr2_01.command("max 16")
    assert check(response, "Ok. max set to 16.0")

    # Tag non-priority
    response = await rr2_01.command("tag 29837FD6")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait... until stable.
    await asyncio.sleep(1100)
    response = await rr2_01.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 16.0 A, energy: 2900 Wh, delay: False, max_usage: 16.0",
    )

    # Last one enters, will tag with a high priority tag (priority 10), but will set a max of 10
    response = await rr2_02.command("max 10")
    assert check(response, "Ok. max set to 10.0")

    response = await rr2_02.command("tag FE7FF01E")
    assert check(response, "Tag Accepted. Parent: , new status: SuspendedEVSE")

    # Wait...
    await asyncio.sleep(300)

    # Check all
    response = await rr2_01.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 16.0 A, energy: 6300 Wh, delay: False, max_usage: 16.0",
    )

    response = await rr2_02.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 12.0 A, energy: 400 Wh, delay: False, max_usage: 10.0",
    )

    response = await rr2_03.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 12.0 A, energy: 7200 Wh, delay: False, max_usage: None",
    )

    response = await rr2_04.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 8.0 A, energy: 4200 Wh, delay: False, max_usage: None",
    )

    _, response = await bz_conn.command("GetChargers", {"group_id": "RR2"})
    assert check_chargers(
        response,
        [
            {
                "charger_id": "TACW224137G670",
                "alias": "RR2-02",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW224537G682",
                "alias": "RR2-03",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW223437G682",
                "alias": "RR2-04",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 1}},
            },
            {
                "charger_id": "TACW224317G584",
                "alias": "RR2-01",
                "connectors": {"1": {"transaction_id": None, "status": "Available", "priority": 3}},
            },
        ],
    )

    # End high priority rr2_01
    response = await rr2_01.command("unplug")
    assert check(response, "Succesfully stopped transaction. id_tag_info: None")

    # Wait...
    await asyncio.sleep(300)

    # Full rr2_02
    response = await rr2_02.command("full")
    assert check(response, "Suspended charging. Status: SuspendedEV")

    # Wait...
    await asyncio.sleep(300)

    # Check all
    response = await rr2_01.command("status")
    assert check(
        response,
        "Status: Available, transaction_id: None, offer: 0.0 A, energy: 0 Wh, delay: False, max_usage: 16.0",
    )
    response = await rr2_02.command("status")
    assert check(
        response,
        "Status: SuspendedEV, transaction_id: 1, offer: 12.0 A, energy: 1100 Wh, delay: True, max_usage: 10.0",
    )

    response = await rr2_03.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 16.0 A, energy: 8200 Wh, delay: False, max_usage: None",
    )

    response = await rr2_04.command("status")
    assert check(
        response,
        "Status: Charging, transaction_id: 1, offer: 8.0 A, energy: 5100 Wh, delay: False, max_usage: None",
    )

    # unplug to stop charging.
    for conn in connections:
        await conn.command("unplug")

    await asyncio.sleep(5)

    # Disconnect from the simulator
    for conn in connections:
        await conn.disconnect()

    # And balanz
    await bz_conn.disconnect()


def main():
    # Run test case outside of pytest
    asyncio.run(test_case1())


if __name__ == "__main__":
    main()
