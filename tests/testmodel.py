import random
import string
import time
from datetime import datetime

from context import balanz
from ocpp.v16.datatypes import IdTagInfo
from ocpp.v16.enums import AuthorizationStatus, ChargePointStatus

from balanz.config import config
from balanz.drawmodel import draw_all
from balanz.model import ChargeChange, Charger, Group, ModelException, Session, Tag, Transaction

config.read("../data/config/balanz.ini")

# --------- Various test helper functions.


def implement_balanz(reduce, grow):
    for c in reduce + grow:
        charger: Charger = Charger.charger_list[c.charger_id]

        # Pseudo do it... DONE
        charger.charge_change_implemented(charge_change=c)
        # test it
        connector = charger.connectors[c.connector_id]
        assert connector.offered == c.allocation
        charger.meter_values(
            connector_id=c.connector_id,
            usage_meter=round(c.allocation - random.random() / 10.0, 3) if c.allocation >= 1.0 else 0,
            energy_meter=2.0,
            timestamp=time.time(),
            offered=c.allocation,
            transaction_id=1,
        )

        assert connector.offered == c.allocation

        if c.allocation > 0.0 and charger.connectors[1].status != ChargePointStatus.charging:
            charger.status_notification(1, ChargePointStatus.charging)
        elif c.allocation == 0.0 and charger.connectors[1].status == ChargePointStatus.charging:
            charger.status_notification(1, ChargePointStatus.suspended_evse)


def balanz_compare(list1, list2, first=True):

    for l1 in list1:
        found_it = False
        for l2 in list2:
            if l1 == l2:
                found_it = True
                break
        if not found_it:
            print("Failed to match")
            print("  ", list1)
            print("  ", list2)
            return False
    if not first:
        return True
    else:
        return balanz_compare(list2, list1, False)


def balanz_assert(test_case, reduce, grow):
    # Write assertion code
    print(f"# TESTCASE: {test_case}")
    print('print("grow", grow)')
    print('print("reduce", reduce)')
    print(f"assert(balanz_compare(reduce, {reduce}))")
    print(f"assert(balanz_compare(grow, {grow}))")


def find_charger(id_or_alias):
    if id_or_alias in Charger.charger_list:
        return Charger.charger_list[id_or_alias]
    else:
        a = [c for c in Charger.charger_list.values() if c.alias == id_or_alias]
        if len(a) > 0:
            return a[0]
    return None


def start(id_or_alias, ev_ready=True):
    charger: Charger = find_charger(id_or_alias)
    if not charger:
        print("No such charger")
        return
    tag = random.choice(list(Tag.tag_list.keys()))
    charger.start_transaction(connector_id=1, id_tag=tag, meter_start=0, timestamp=time.time())
    time.sleep(0.5)
    if ev_ready:
        charger.status_notification(connector_id=1, status=ChargePointStatus.suspended_evse)
    else:
        charger.status_notification(connector_id=1, status=ChargePointStatus.suspended_ev)
    print(draw_all(historic=True))


def stop(id_or_alias, meter_stop=None):
    charger: Charger = find_charger(id_or_alias)
    if not charger:
        print("No such charger")
        return
    trans: Transaction = charger.connectors[1].transaction
    if trans == None:
        print("Not in transaction.")
        return
    if meter_stop == None:
        meter_stop = trans.energy_meter + 20 if trans.energy_meter != None else 30  # Wh
    charger.stop_transaction(transaction_id=1, meter_stop=meter_stop, timestamp=time.time(), reason="EV Disconnected")
    time.sleep(0.5)
    charger.status_notification(connector_id=1, status=ChargePointStatus.available)
    print(draw_all(historic=True))


def status(id_or_alias, status):
    charger: Charger = find_charger(id_or_alias)
    if not charger:
        print("No such charger")
        return
    charger.status_notification(connector_id=1, status=status)
    print(draw_all(historic=True))


def meter(id_or_alias, usage_meter, energy_meter=None):
    charger: Charger = find_charger(id_or_alias)
    if not charger:
        print("No such charger")
        return
    trans: Transaction = charger.connectors[1].transaction
    if trans == None:
        print("Not in transaction.")
        return
    if energy_meter == None:
        energy_meter = trans.energy_meter + 10  # Wh
    charger.meter_values(
        connector_id=1,
        usage_meter=usage_meter,
        energy_meter=energy_meter,
        timestamp=time.time(),
        offered=trans.offered,
        transaction_id=1,
    )
    print(draw_all(historic=True))


def balanz(group_id):
    if not group_id in Group.group_list:
        print("No such group")
        return
    group: Group = Group.group_list[group_id]
    reduce, grow = group.balanz()
    print("  Reduce", reduce)
    print("  Grow", grow)
    implement_balanz(reduce, grow)
    print(drawmodel.draw_group(group, historic=True))


def help():
    print("Instructions for interactive mode")
    print(
        "start(<charger-id or alias>, [EV ready (True/False)])  # Default EV is ready, otherwise put False. A random tag will be used."
    )
    print("stop(<charger-id or alias), [<meter_stop>]    Reason fixed to EV Disconnected")
    print("meter(<charger-id or alias>, usage, [energy])")
    print("status(<charger-id or alias>, status)   e.g. suspended_ev")
    print("balanz(<group>)")
    print("help()   This message")


# -------- READ SOME CSV
def head(header):
    return "".join([h for h in header if h in string.ascii_letters])


def parse_time(t):
    return datetime.strptime(t, "%d/%m/%Y %H:%M")


def _sn(val):
    return val if val != "" else None


def _in(val):
    return int(val) if val != "" else None


Group.read_csv("../data/model/groups.csv")

# Test some error handling
try:
    Group("FAIL", parent_id="NOT", description="RR3 Chargers", max_allocation=16)
except ModelException as error:
    print("Failed to create FAIL group", error.value)

try:
    Charger(charger_id="FAIL", alias="FAIL-ALIAS", group_id="NOSUCH")
except ModelException as error:
    print("Failed to create FAIL charger", error.value)

# Let's create a charger and remove again to ensure nothing left over
ghost = Charger(
    charger_id="GHOST",
    alias="Ghost entry should should go away",
    group_id="RR1",
    description="A ghost - short lived",
)
ghost.remove()

Tag.read_csv("../data/model/tags.csv")
Charger.read_csv("../data/model/chargers.csv")

print(draw_all())
