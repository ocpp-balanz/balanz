"""
Utility functions for drawing the model ascii art style.

Results are strings using '\n' as line separators.
"""

import time

from model import Charger, ChargingHistory, Connector, Group, Session
from util import schedule_value_now_external, time_str


def draw_charge_history(charging_history: list[ChargingHistory], prefix: str = "") -> str:
    s = ""
    if charging_history:
        s += f"{prefix} |       "
        s += ", ".join([f"@{time_str(ch.timestamp)}={ch.offered}A" for ch in charging_history]) + "\n"
    return s


def draw_connector(connector: Connector, prefix: str = "", historic: bool = False) -> str:
    s = f"{prefix} |  > {connector.connector_id}: status: {connector.status}, offer: {connector.offered} A"
    if connector.transaction:
        s += (
            f", pri: {connector.conn_priority()}, usage: {connector.transaction.usage_meter}, id_tag: "
            f"{connector.transaction.id_tag}"
            f"{' (' + connector.transaction.user_name + ')' if connector.transaction.user_name else ''}, "
            f"start: {time_str(connector.transaction.start_time)}, energy: {connector.transaction.energy_meter} Wh, "
            f"last_usage: {time_str(connector.transaction.last_usage_time)}"
        )
        if connector.transaction._bz_ev_max_usage is not None:
            s += f", max_ev: {connector.transaction._bz_ev_max_usage}"
        if connector.transaction._bz_suspend_until is not None:
            s += f", suspend_until: {time_str(connector.transaction._bz_suspend_until)}"
    s += "\n"
    if connector.transaction and historic:
        s += draw_charge_history(charging_history=connector.transaction.charging_history, prefix=prefix)
        # History for this transaction ?
    return s


def draw_charger(charger: Charger, historic: bool = False, prefix: str = "") -> str:
    s = ""
    # Charger header/info
    s += (
        f'{prefix} |- {charger.charger_id} {"(" + charger.alias + ")" if charger.alias != "" else ""}"'
        f'/{"C" if hasattr(charger, "ocpp_ref") and charger.ocpp_ref is not None else "NC"} {charger.description}, '
        f'priority: {charger.priority}, ' 
        f"firmware: {charger.firmware_version}, updated: {time_str(charger.last_update)}, "
        f"conn_max: {charger.conn_max} A\n"
    )
    for conn in charger.connectors.values():
        s += draw_connector(connector=conn, prefix=prefix, historic=historic)
    if historic:
        completed_sessions = [
            s for s in Session.session_list.values() if s.charger_id == charger.charger_id and s.end_time is not None
        ]
        completed_sessions.sort(key=lambda x: x.start_time, reverse=True)
        for session in completed_sessions:
            s += (
                f"{prefix}      |-DONE: {session.session_id}, id_tag {session.id_tag} ({session.user_name}),"
                f" start: {time_str(session.start_time)}, end: {time_str(session.end_time)}, "
                f"energy: {session.energy_meter / 1000:.4f} kWh, reason: {session.reason}\n"
            )
            s += draw_charge_history(charging_history=session.charging_history, prefix=prefix)
    return s


def draw_group(group: Group, historic: bool = False, prefix: str = "") -> str:
    s = ""

    # Group header/info
    s += f"{prefix}Group {group.group_id} ({group.description}),"
    s += f" max_allocation: {schedule_value_now_external(group._max_allocation)}, usage: {group.usage():.2f},"
    s += f" offered: {group.offered()} A\n"

    # Chargers
    for c in sorted(
        group.chargers.values(),
        key=lambda x: x.alias if x.alias is not None else x.charger_id,
    ):
        s += draw_charger(charger=c, historic=historic, prefix=prefix)
    return s


def draw_all(historic: bool = False) -> str:
    """draw everything in the system"""
    headerline = f"Balanz groups status as of {time_str(time.time())}\n"
    return headerline + "".join([draw_group(g, historic) for g in Group.group_list.values()])
