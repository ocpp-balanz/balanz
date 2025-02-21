"""
balanz API. Exposes a WebSocket based protocol parallel to the OCPP protocol
used with Charger/Servers.

Refer to the documentation for a list of supported calls.
"""

import json
import logging

import drawmodel
import websockets
import websockets.asyncio
import websockets.asyncio.server
from config import config
from model import Charger, Group, Session, Tag
from ocpp.messages import MessageType
from ocpp.v16 import call_result
from ocpp.v16.enums import (
    ChargingProfileStatus,
    ClearChargingProfileStatus,
    ConfigurationStatus,
    RemoteStartStopStatus,
    ResetStatus,
    ResetType,
    TriggerMessageStatus,
)
from util import gen_sha_256

logger = logging.getLogger("api")


async def api_handler(websocket):
    """Handler for the API"""
    logged_in: bool = False

    # Command/Call loop
    while True:
        try:
            message = await websocket.recv()
            call = json.loads(message)
            result = None

            if len(call) != 4 or call[0] != MessageType.Call:
                logger.error(f"API call malformed: {call}")
                result = [MessageType.CallError, "007", {"status": "ProtocolError"}]
            else:
                message_id = call[1]
                command = call[2]
                payload = call[3]

                # Log call, but not Login (security) and DrawAll (noisy)
                if command not in ["Login", "DrawAll"]:
                    logger.info(f"API command received: {command} {message_id} {payload}")

                # Handle logon directly
                if not logged_in and command != "Login":
                    result = [MessageType.CallError, message_id, {"status": "NotAuthorized"}]

                # Resolve charger alias for all calls quietly by adapting payload
                if payload != None and payload != "":
                    alias = payload.get("alias", None)
                    if alias and not "charger_id" in payload:
                        id = [c.charger_id for c in Charger.charger_list.values() if c.alias == alias]
                        if len(id) == 1:
                            payload["charger_id"] = id[0]

                # Common check for charger specified by id, known, and connected
                if not result and command in [
                    "ClearDefaultProfiles",
                    "ClearDefaultProfile",
                    "SetDefaultProfile",
                    "SetTxProfile",
                    "Reset",
                    "RemoteStartTransaction",
                    "RemoteStopTransaction",
                    "GetConfiguration",
                    "ChangeConfiguration",
                    "TriggerMessage",
                    "SetChargePriority",
                ]:
                    charger_id = payload.get("charger_id", None)

                    if not charger_id or charger_id not in Charger.charger_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchCharger"},
                        ]
                    else:
                        charger: Charger = Charger.charger_list[charger_id]
                        if not charger.ocpp_ref:
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": "ChargerNotConnected"},
                            ]
                        else:
                            charger: Charger = Charger.charger_list[charger_id]

                # The commands
                if not result and command == "Login":
                    token = payload.get("token", None)
                    token_shas = config.get("api", "token_shas")
                    if not token or not token_shas or not gen_sha_256(token) in token_shas.split(","):
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "InvalidLogin"},
                        ]
                    else:
                        result = [MessageType.CallResult, message_id, {"status": "Accepted"}]
                        logged_in = True
                elif not result and command == "GetStatus":
                    # TODO: Add more
                    result = [MessageType.CallResult, message_id, {"version": config.get("balanz", "version")}]
                elif not result and command == "DrawAll":
                    historic = payload.get("historic", True)
                    drawing = drawmodel.draw_all(historic=historic)
                    result = [MessageType.CallResult, message_id, {"drawing": drawing}]
                elif not result and command == "GetGroups":
                    charger_details = payload.get("charger_details", False)
                    result = [
                        MessageType.CallResult,
                        message_id,
                        [g.external(charger_details) for g in Group.group_list.values()],
                    ]
                elif not result and command == "ReloadGroups":
                    Group.read_csv(config["model"]["groups_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "WriteGroups":
                    Group.write_csv(config["model"]["groups_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "UpdateGroup":
                    group_id = payload.get("group_id", None)
                    description = payload.get("description", None)
                    max_allocation = payload.get("max_allocation", None)
                    if group_id is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif group_id not in Group.group_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchGroup"},
                        ]
                    else:
                        Group.group_list[group_id].update(description=description, max_allocation=max_allocation)
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "GetChargers":
                    charger_id = payload.get("charger_id", None)
                    group_id = payload.get("group_id", None)

                    if group_id:
                        if group_id not in Group.group_list:
                            charger_list = []  # Or, NoSuchGroup?
                        else:
                            charger_list: Group = Group.group_list[group_id].all_chargers()
                    else:
                        charger_list = Charger.charger_list.values()

                    chargers = [c for c in charger_list if charger_id and charger_id == c.charger_id or not charger_id]
                    result = [MessageType.CallResult, message_id, [c.external() for c in chargers]]
                elif not result and command == "ReloadChargers":
                    Charger.read_csv(config["model"]["chargers_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "WriteChargers":
                    Charger.write_csv(config["model"]["chargers_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "UpdateCharger":
                    charger_id = payload.get("charger_id", None)
                    alias = payload.get("alias", None)
                    priority = payload.get("priority", None)
                    description = payload.get("description", None)
                    conn_max = payload.get("conn_max", None)
                    if charger_id is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif charger_id not in Charger.charger_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchCharger"},
                        ]
                    else:
                        Charger.charger_list[charger_id].update(
                            alias=alias, priority=priority, description=description, conn_max=conn_max
                        )
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "GetTags":
                    result = [MessageType.CallResult, message_id, [t.external() for t in Tag.tag_list.values()]]
                elif not result and command == "ReloadTags":
                    Tag.read_csv(config["model"]["tags_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "WriteTags":
                    Tag.write_csv(config["model"]["tags_csv"])
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {"status": "Accepted"},
                    ]
                elif not result and command == "UpdateTag":
                    id_tag = payload.get("id_tag", None)
                    user_name = payload.get("user_name", None)
                    parent_id_tag = payload.get("parent_id_tag", None)
                    description = payload.get("description", None)
                    status = payload.get("status", None)
                    priority = payload.get("priority", None)
                    if id_tag is not None:
                        id_tag = id_tag.upper()
                    if id_tag is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif id_tag not in Tag.tag_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchTag"},
                        ]
                    else:
                        Tag.tag_list[id_tag].update(
                            user_name=user_name,
                            parent_id_tag=parent_id_tag,
                            description=description,
                            status=status,
                            priority=priority,
                        )
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "CreateTag":
                    id_tag = payload.get("id_tag", None)
                    user_name = payload.get("user_name", None)
                    parent_id_tag = payload.get("parent_id_tag", None)
                    description = payload.get("description", None)
                    status = payload.get("status", None)
                    priority = payload.get("priority", None)
                    if id_tag is not None:
                        id_tag = id_tag.upper()
                    if id_tag is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif id_tag in Tag.tag_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "TagExists"},
                        ]
                    else:
                        Tag(
                            id_tag=id_tag,
                            user_name=user_name,
                            parent_id_tag=parent_id_tag,
                            description=description,
                            status=status,
                            priority=priority,
                        )
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "DeleteTag":
                    id_tag = payload.get("id_tag", None)
                    if id_tag is not None:
                        id_tag = id_tag.upper()
                    if id_tag is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif id_tag not in Tag.tag_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchTag"},
                        ]
                    else:
                        del Tag.tag_list[id_tag]
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "SetLogLevel":
                    component = payload.get("component", None)
                    loglevel = payload.get("loglevel", None)
                    if not component or not loglevel:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "IllegalArguments"},
                        ]
                    elif component not in config["logging"]:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchComponent"},
                        ]
                    else:
                        logging.getLogger(component).setLevel(level=loglevel)
                        logger.info(f"Updated log level for {component} to {loglevel}")
                        result = [MessageType.CallResult, message_id, {"status": "Accepted"}]
                elif not result and command == "GetSessions":
                    charger_id = payload.get("charger_id", None)
                    group_id = payload.get("group_id", None)
                    charger_list = None
                    if group_id:
                        charger_list = [c.charger_id for c in Charger.charger_list.values() if c.is_in_group(group_id)]
                    elif charger_id:
                        charger_list = [charger_id]
                    sessions = [
                        s for s in Session.session_list.values() if charger_list is None or s.charger_id in charger_list
                    ]
                    result = [MessageType.CallResult, message_id, [s.external() for s in sessions]]
                elif not result and command == "SetBalanzState":
                    balanz_suspend = payload.get("suspend", False)
                    group_id = payload.get("group_id", None)
                    if not group_id or group_id not in Group.group_list:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchGroup"},
                        ]
                    else:
                        group: Group = Group.group_list[group_id]
                        if not group.is_allocation_group():
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": "NotAllocationGroup"},
                            ]
                        else:
                            group._bz_suspend = balanz_suspend
                            logger.info(f"balanz suspend state {balanz_suspend} for group {group_id}")
                            result = [
                                MessageType.CallResult,
                                message_id,
                                {"status": "Accepted"},
                            ]
                elif not result and command == "SetChargePriority":
                    connector_id = payload.get("connector_id", 1)
                    priority = payload.get("priority", None)
                    if priority is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "PriorityNotSupplied"},
                        ]
                    elif connector_id not in charger.connectors:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "NoSuchConnector"},
                        ]
                    elif charger.connectors[connector_id].transaction is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "ConnectorNotInTransaction"},
                        ]
                    else:
                        charger.connectors[connector_id].transaction.priority = priority
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "ClearDefaultProfiles":
                    c_result = await charger.ocpp_ref.clear_all_default_profiles()
                    if c_result.status != ClearChargingProfileStatus.accepted:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": c_result.status},
                        ]
                    else:
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "ClearDefaultProfile":
                    connector_id = payload.get("connector_id", 1)
                    charging_profile_id = payload.get("charging_profile_id", None)

                    c_result = await charger.ocpp_ref.clear_charging_profile_req(
                        id=charging_profile_id, connector_id=connector_id
                    )
                    if c_result.status != ClearChargingProfileStatus.accepted:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": c_result.status},
                        ]
                    else:
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "SetDefaultProfile":
                    connector_id = payload.get("connector_id", 1)
                    charging_profile_id = payload.get("charging_profile_id", None)
                    stack_level = payload.get("stack_level", 1)
                    limit = payload.get("limit", None)

                    if not charging_profile_id or limit is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "InvalidParameters"},
                        ]
                    else:
                        c_result = await charger.ocpp_ref.set_default_profile(
                            connector_id=connector_id,
                            charging_profile_id=charging_profile_id,
                            stack_level=stack_level,
                            limit=limit,
                        )
                        if c_result.status != ChargingProfileStatus.accepted:
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": c_result.status},
                            ]
                        else:
                            result = [
                                MessageType.CallResult,
                                message_id,
                                {"status": "Accepted"},
                            ]
                elif not result and command == "SetTxProfile":
                    connector_id = payload.get("connector_id", 1)
                    transaction_id = payload.get("transaction_id", 1)
                    limit = payload.get("limit", None)

                    if limit is None:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "InvalidParameters"},
                        ]
                    else:
                        c_result = await charger.ocpp_ref.set_tx_profile(
                            connector_id=connector_id,
                            transaction_id=transaction_id,
                            limit=limit,
                        )
                        if c_result.status != ChargingProfileStatus.accepted:
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": c_result.status},
                            ]
                        else:
                            result = [
                                MessageType.CallResult,
                                message_id,
                                {"status": "Accepted"},
                            ]
                elif not result and command == "Reset":
                    reset_type = payload.get("type", ResetType.soft)
                    c_result = await charger.ocpp_ref.reset_req(type=reset_type)
                    if c_result.status != ResetStatus.accepted:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": c_result.status},
                        ]
                    else:
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": "Accepted"},
                        ]
                elif not result and command == "RemoteStartTransaction":
                    id_tag = payload.get("id_tag", None)
                    connector_id = payload.get("connector_id", None)

                    if not id_tag or not connector_id:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "InvalidParameters"},
                        ]
                    else:
                        c_result = await charger.ocpp_ref.remote_start_transaction_req(
                            id_tag=id_tag, connector_id=connector_id
                        )
                        if c_result.status != RemoteStartStopStatus.accepted:
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": c_result.status},
                            ]
                        else:
                            result = [
                                MessageType.CallResult,
                                message_id,
                                {"status": "Accepted"},
                            ]
                elif not result and command == "RemoteStopTransaction":
                    transaction_id = payload.get("transaction_id", None)

                    if not transaction_id:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": "InvalidParameters"},
                        ]
                    else:
                        c_result = await charger.ocpp_ref.remote_stop_transaction_req(transaction_id=transaction_id)
                        if c_result.status != RemoteStartStopStatus.accepted:
                            result = [
                                MessageType.CallError,
                                message_id,
                                {"status": c_result.status},
                            ]
                        else:
                            result = [
                                MessageType.CallResult,
                                message_id,
                                {"status": "Accepted"},
                            ]
                elif not result and command == "GetConfiguration":
                    key_list = payload.get("key", None)
                    c_result: call_result.GetConfiguration = await charger.ocpp_ref.get_configuration_req(key=key_list)
                    result = [
                        MessageType.CallResult,
                        message_id,
                        {
                            "configuration_key": c_result.configuration_key,
                            "unknown_key": c_result.unknown_key,
                        },
                    ]
                elif not result and command == "ChangeConfiguration":
                    key_list = payload.get("key", None)
                    c_result: call_result.ChangeConfiguration = await charger.ocpp_ref.change_configuration_req(
                        key=key_list, value=payload.get("value", None)
                    )
                    if c_result.status != ConfigurationStatus.accepted:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": c_result.status},
                        ]
                    else:
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": c_result.status},
                        ]
                elif not result and command == "TriggerMessage":
                    requested_message = payload.get("requested_message", None)
                    connector_id = payload.get("connector_id", 1)

                    c_result: call_result.TriggerMessage = await charger.ocpp_ref.trigger_message_req(
                        requested_message=requested_message,
                        connector_id=connector_id,
                    )
                    if c_result.status != TriggerMessageStatus.accepted:
                        result = [
                            MessageType.CallError,
                            message_id,
                            {"status": c_result.status},
                        ]
                    else:
                        result = [
                            MessageType.CallResult,
                            message_id,
                            {"status": c_result.status},
                        ]
                elif not result:
                    result = [
                        MessageType.CallError,
                        message_id,
                        f"Invalid Command {command}",
                    ]
            if command != "DrawAll":
                logger.info(f"API response: {result}")
            await websocket.send(json.dumps(result))

        except websockets.exceptions.ConnectionClosed:
            logger.info("API connection closed")
            break
        except Exception as error:
            logger.info(f"While processing API command, an error occurred: {error}")
            result = [MessageType.CallError, "007", "Unexpected Error"]
            await websocket.send(json.dumps(result))
