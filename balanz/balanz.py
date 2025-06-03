"""
Balanz. Simple CSMS or LC with Load Balancing capabilities.
"""

import argparse
import asyncio
import base64
import importlib.metadata
import logging
import ssl
import time

import websockets
import websockets.asyncio
import websockets.asyncio.server
from api import api_handler
from audit_logger import audit_logger
from charge_point_csms_v16 import ChargePoint_CSMS_v16
from charge_point_lc_v16 import ChargePoint_LC_v16
from config import config
from memory_log_handler import MemoryLogHandler
from model import ChargeChange, Charger, Connector, Group, Session, Tag, Transaction
from ocpp.v16.enums import ChargePointStatus, ChargingProfileStatus, ClearChargingProfileStatus, Reason
from user import User
from util import gen_sha_256, time_str
from websockets.frames import CloseCode

balanz_version = importlib.metadata.version("balanz")

# #################################################
# Set-up logging stuff
formatter = logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Console (stderr)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# In-memory handler
log_memory_handler = MemoryLogHandler(capacity=100000)
log_memory_handler.setLevel(logging.INFO)
log_memory_handler.setFormatter(formatter)
log_memory_handler.set_api_intance()

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(log_memory_handler)

logger = logging.getLogger("balanz")


# TODO: Should some checking be delegated here?
async def process_request(connection: websockets.asyncio.server.ServerConnection, request):
    logger.info(f"connection from {connection.remote_address}, request: {request}")
    return None


async def on_connect(websocket: websockets.asyncio.server.ServerConnection):
    """Entry point for CP connection.

    Chargers are expected to connect with their ID as the final part of the URL. Clients
    connect to the api endpoint.

    ClosedCodes are used for closing/rejecting, see https://www.rfc-editor.org/rfc/rfc6455.html#section-7.1.5
    """
    path = websocket.request.path
    if path.strip("/") == "api":
        await api_handler(websocket)  # Delegate to API handler
        return

    # Big hack for Javascript support.
    # See https://stackoverflow.com/questions/4361173/http-headers-in-websockets-client-api, suggestion 5
    # If option is set, will allow the a hex representation of the encoded authentication field to be sent
    # as a dummy protocol value.
    if config.getboolean("host", "http_auth_via_protocol") and "Authorization" not in websocket.request.headers:
        requested_protocols = websocket.request.headers["Sec-WebSocket-Protocol"]
        for prot in requested_protocols.split(","):
            if not prot.startswith("ocpp"):
                # Convert from hex to base64 encoding
                auth_data: str = base64.b64encode(bytearray.fromhex(prot.strip())).decode()
                websocket.request.headers["Authorization"] = "Basic " + auth_data
                logger.debug(f'Setting Authorization from protocol field to "{auth_data}"')
                break

    # Check if charger present in model and if to possibly auto-register
    charger_id = path.strip("/")
    if charger_id not in Charger.charger_list:
        if config.getboolean("model", "charger_autoregister"):
            auto_group_id = config.get("model", "charger_autoregister_group")

            # Auto-register it the charger. Need to "invent" an alias
            Charger(charger_id=charger_id, group_id=auto_group_id, alias=charger_id)
        else:
            msg = f"Charge point {charger_id} unknown"
            logger.error(msg)
            return await websocket.close(CloseCode.INVALID_DATA, msg)

    charger: Charger = Charger.charger_list[charger_id]
    tasks = []
    if config.has_option("ext-server", "server"):
        # LC/proxy mode

        # Try connecting to server
        server = config["ext-server"]["server"]
        server_url = server + charger_id
        try:
            logger.debug(f"headers: {websocket.request.headers}")

            # Forward any Authorization header
            headers = {}
            if "Authorization" in websocket.request.headers:
                headers["Authorization"] = websocket.request.headers["Authorization"]
                logger.debug(f'Authorization header set to {headers["Authorization"]}')
            user_agent = websocket.request.headers.get("User-Agent", None)  # TODO: Make configurable?

            server_connection = await websockets.connect(
                uri=server_url,
                user_agent_header=user_agent,
                additional_headers=headers,
                subprotocols=["ocpp1.6"],
            )
            logger.info(f"Connected to upstream server @ {server_url}")
        except Exception as e:
            logger.error(f"Failed to connected to upstream server @ {server_url}: {e}")
            return await websocket.close(CloseCode.ABNORMAL_CLOSURE, "Failed to connect to upstream server")

        # Instantiate LC ChargePoint and start required tasks; one watchdog, upstream task, downstream task
        cp = ChargePoint_LC_v16(
            server_connection=server_connection,
            charger=charger,
            id=charger_id,
            connection=websocket,
        )
        tasks.append(asyncio.create_task(cp.watchdog()))
        tasks.append(asyncio.create_task(cp.start_lc_up()))
        tasks.append(asyncio.create_task(cp.start_lc_down()))
    else:
        # CSMS mode

        # Handle HTTP basic auth..
        http_auth_init_new_key = False
        if config.getboolean("host", "http_auth"):
            # Debug
            if "Authorization" in websocket.request.headers:
                auth_data = websocket.request.headers["Authorization"].split()[1]
                auth_value = base64.b64decode(auth_data).decode("utf-8")
                logger.debug(f"Basic authentication received. Decode base64 value is {auth_value}")

            # If charger has SHA set, need to compare against that.
            if charger.auth_sha:
                request_auth = websocket.request.headers.get("Authorization", None)
                if not request_auth:
                    msg = "Rejected connection due to missing Basic Auth"
                    logger.warning(msg)
                    return await websocket.close(CloseCode.POLICY_VIOLATION, msg)

                request_auth_sha = gen_sha_256(request_auth)
                if charger.auth_sha != request_auth_sha:
                    logger.error(
                        f"Rejected connection due to wrong Basic Auth. {request_auth_sha} vs {charger.auth_sha}"
                    )
                    return await websocket.close(CloseCode.POLICY_VIOLATION, reason="Authentization error")
            else:
                http_auth_init_new_key = True

        # Instantiate CSMS ChargePoint and start required tasks; watchdog and central CP CSMS loop
        cp = ChargePoint_CSMS_v16(charger=charger, id=charger_id, connection=websocket)
        tasks.append(asyncio.create_task(cp.watchdog()))
        tasks.append(asyncio.create_task(cp.start()))

        # HTTP AuthorizationKey generation. If required, will spawn a task that will run once to do this.
        if http_auth_init_new_key:
            asyncio.create_task(cp.set_new_authorizationkey())

    # Store reference to cp on charger (to be used for all communications)
    charger.ocpp_ref = cp
    charger.requested_status = False
    logger.info(f"Charger {charger_id} ({charger.alias}) succesfully connected.")

    # Wait for tasks to complete
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    logger.debug(f"Task(s) completed for {charger_id}: {done}, {pending}")

    for task in done:
        e = task.exception()
        if e:
            logger.warning(
                f"{charger_id} ({charger.alias}) (Not serious - likely connection loss) Task {task} raised exception {e} related to charger "
            )

    # Cancel any remaining tasks
    for task in pending:
        task.cancel()

    # Finally, clear stuff.
    logger.info(f"Charger {charger_id} ({charger.alias}) stopped. Closing connection")
    cp.charger = None
    charger.ocpp_ref = None
    # Note, on purpose NOT clearing charger.last_update as this will be used to determine if to invalidate transactions.
    return await websocket.close(CloseCode.GOING_AWAY)


async def balanz_loop(group: Group):
    """balanz (smart charging) control loop.

    There will be one loop running as a task per allocation group. This loop will call the balanz() function on
    the group at the interval configured and then proceed to implement any allocation/offer changes requested.

    loop will run every "run_interval" seconds (default 5 seconds) to check for more urgent events.
    These include new chargers to be initialized, or the detection of new charging sessions (as indicated by a flag
    on the connector).

    Once every "intervals_full" times (default 12, so once every minute), a full run will be done regardless.
    """

    # Initial delay before loop. This allows things to startup nicely.
    await asyncio.sleep(config.getint("balanz", "first_wait"))

    loop_count = 0
    intervals_full = config.getint("balanz", "intervals_full")
    while True:
        await asyncio.sleep(config.getint("balanz", "run_interval"))

        loop_count += 1
        # Time to do stuff? Either because it is time, or because urgent things to do.
        if (
            (loop_count % intervals_full != 0)
            and not group.chargers_not_init()
            and not group.connectors_balanz_review()
        ):
            continue

        try:
            # Suspended?
            if group._bz_suspend:
                logger.debug(f"Group {group.group_id} suspended. Skipping balanz run.")
                continue

            logger.debug(f"Balanz run for group {group.group_id}. Run interval loop count {loop_count}")

            # First, check if any chargers not yet initialized. This is a priority to ensure that chargers
            # do not independently make allocations.
            chargers_to_initialize = group.chargers_not_init()
            if chargers_to_initialize:
                logger.info(
                    f'Group {group.group_id}. Chargers to init {",".join(c.charger_id for c in chargers_to_initialize)}'
                )
                # Set charger default state(s) case.
                for charger in chargers_to_initialize:
                    # Check valid ocpp_ref
                    if not charger.ocpp_ref:
                        logger.warning(f"While trying to initialize {charger.charger_id} no ocpp_ref was set.")
                        continue

                    # First clear any profiles
                    result = await charger.ocpp_ref.clear_all_default_profiles()
                    if result.status != ClearChargingProfileStatus.accepted:
                        logger.warning(
                            f"Failed to clear default profiles for {charger.charger_id}. Result: {result.status}"
                        )

                    # Blocking profile(s) first
                    for connector_id in range(1, len(charger.connectors) + 1):
                        result = await charger.ocpp_ref.set_blocking_default_profile(connector_id=connector_id)
                        if result.status != ChargingProfileStatus.accepted:
                            logger.warning(
                                f"Failed to set blocking default profile for {charger.charger_id}/{connector_id} ({charger.alias})."
                                f" Result: {result.status}"
                            )
                            # TODO: Check error handling

                    # Then base profile
                    result = await charger.ocpp_ref.set_base_default_profile()
                    if result.status != ChargingProfileStatus.accepted:
                        logger.warning(
                            f"Failed to set base default profile for {charger.charger_id} ({charger.alias}). Result: {result.status}"
                        )

                    logger.info(f"Succesfully cleared and set default profiles for {charger.charger_id} ({charger.alias})")

                    charger.profile_initialized = True
                # Give some time, by rerunning loop before calling balanz()
                continue

            # Quick check for any chargers recently (re)connected where we should ask status
            chargers_to_request_status = group.chargers_to_request_status()
            if chargers_to_request_status:
                for charger in chargers_to_request_status:
                    await charger.ocpp_ref.trigger_boot_notification()
                    for connector_id in charger.connectors:
                        await charger.ocpp_ref.trigger_status_notification(connector_id=connector_id)
                    await charger.ocpp_ref.trigger_meter_values()
                    charger.requested_status = True

            # Quick check to see any connectors for some reason have not reset the blocking profile but
            # are in a non transactional situation. We will not be hard on errors in case blocking profile
            # may be there anyways...
            reset_connectors: list[Connector] = group.connectors_reset_blocking()
            for conn in reset_connectors:
                result = await conn.charger.ocpp_ref.set_blocking_default_profile(connector_id=conn.connector_id)
                if result.status != ChargingProfileStatus.accepted:
                    logger.warning(
                        f"Failed to reset blocking default profile for {conn.id_str()}" f" Result: {result.status}"
                    )
                else:
                    logger.debug(f"Ok reset blocking default profile for {conn.id_str()}")
                # Note, doing this regardless of result. That is on purpose!
                conn._bz_blocking_profile_reset = True

            # Next, check for any transactions that have started, but where the default blocking profiles needs
            # to be reinstated. For these, we first need to set a TxProfile to match the base profile, and then
            # reset the blocking TxDefaultProfile
            reset_transactions: list[Transaction] = group.transactions_reset_blocking()
            for trans in reset_transactions:
                charger: Charger = Charger.charger_list[trans.charger_id]

                result = await charger.ocpp_ref.set_tx_profile(
                    connector_id=trans.connector_id,
                    transaction_id=trans.transaction_id,
                    limit=config.getint("balanz", "min_allocation"),
                )
                if result.status != ChargingProfileStatus.accepted:
                    logger.warning(f"TxProfile initial setup failed for {trans.id_str()}. Result: {result.status}")
                else:
                    # Report this as a change to ensure included in history
                    charger.charge_change_implemented(
                        ChargeChange(
                            charger_id=charger.charger_id,
                            connector_id=trans.connector_id,
                            transaction_id=trans.transaction_id,
                            allocation=config.getint("balanz", "min_allocation"),
                        )
                    )

                    result = await charger.ocpp_ref.set_blocking_default_profile(connector_id=trans.connector_id)
                    if result.status != ChargingProfileStatus.accepted:
                        logger.warning(
                            f"Failed to reset blocking default profile for {trans.id_str()}."
                            f" Result: {result.status}"
                        )
                    else:
                        logger.debug(
                            f"Ok TxProfile/reset blocking default profile for {trans.id_str()}."
                        )
                trans.connector._bz_blocking_profile_reset = True  # TODO: This can be dangerous, should it be break?

            # Actual rebalancing. First reduce, wait a little (configurable), then grow
            reduce_list, grow_list = group.balanz()
            # Hack. If there are reduce changes, add a fake final change element. This will drive waiting
            if reduce_list and grow_list:
                reduce_list.append(
                    ChargeChange(
                        charger_id="_WAIT_",
                        connector_id=None,
                        transaction_id=None,
                        allocation=None,
                    )
                )
            for change in reduce_list + grow_list:
                if change.charger_id == "_WAIT_":
                    # Wait for a little bit before continuing
                    await asyncio.sleep(config.getint("balanz", "wait_after_reduce"))
                    continue

                charger: Charger = Charger.charger_list[change.charger_id]
                # Check valid ocpp_ref
                if not charger.ocpp_ref:
                    logger.warning(f"Skipping charging change for charger {charger.charger_id} ({charger.alias}) as no ocpp_ref set.")
                    continue  # TODO: Potentally dangerous

                if change.transaction_id is None:
                    # Special case when transaction_id is not yet known.

                    # This will normally be the "starting case" which will be addressed by removing the blocking profile.
                    # However, if that was attempted and did not result in a transaction starting, it may be necessary
                    # to reinstate the blocking profile...
                    # Which situation is it?
                    if change.allocation == 0:
                        result = await charger.ocpp_ref.set_blocking_default_profile(change.connector_id)
                        if result.status != ChargingProfileStatus.accepted:
                            logger.warning(
                                f"Failed to set blocking default profile to do {change} ({charger.alias})"
                                f" Result: {result.status}. Aborting further changes"
                            )
                            break
                    else:
                        result = await charger.ocpp_ref.clear_blocking_default_profile(change.connector_id)
                        if result.status != ClearChargingProfileStatus.accepted:
                            logger.warning(
                                f"Failed to implement balanz change {change} ({charger.alias}) by deleting blocking profile."
                                f" Result: {result.status}. Continuing with other changes regardless"
                            )
                        else:
                            conn: Connector = charger.connectors[change.connector_id]
                            logger.debug(f"Cleared blocking profile for {conn.id_str()}")
                            conn._bz_blocking_profile_reset = False
                else:
                    # Normal case, change is done by updating TxProfile
                    result = await charger.ocpp_ref.set_tx_profile(
                        connector_id=change.connector_id,
                        transaction_id=change.transaction_id,
                        limit=change.allocation,
                    )
                    if result.status != ChargingProfileStatus.accepted:
                        logger.warning(
                            f"Failed to implement change {change} ({charger.alias}). Result: {result.status}. Aborting further changes.."
                        )
                        break

                logger.info(f"Succesfully implemented balanz change {change} ({charger.alias})")

                # Report change back to model
                charger.charge_change_implemented(change)

        except Exception as e:
            logger.error(f"Exception {e} in balanz_loop. Retrying")


async def model_watchdog():
    """model watchdog to check for stale transactions."""

    logger.info("model_watchdog started.")
    while True:
        await asyncio.sleep(config.getint("csms", "transaction_interval"))
        try:
            # ---- First, timeout any allocations for chargers that have not updated recently (as defined by config)
            for c in Charger.charger_list.values():
                if c.last_update is None or time.time() - c.last_update > config.getint("csms", "transaction_timeout"):
                    for connector in c.connectors.values():
                        if connector.transaction:
                            logger.warning(
                                f"Pseudo-stopping transaction {connector.transaction.id_str()} "
                                f"as not heard from since {time_str(c.last_update)}"
                            )
                            c.stop_transaction(
                                transaction_id=connector.transaction.transaction_id,
                                meter_stop=connector.transaction.energy_meter,
                                timestamp=time.time(),
                                reason=Reason.other,
                            )
                            connector.status = ChargePointStatus.available
        except Exception as e:
            logger.error(f"Exception {e.message} in model_watchdog loop. Retrying")


async def main():
    """main. Argument parsing and startup."""
    logger.warning(f"Balanz version {balanz_version}")

    # Argument stuff.
    parser = argparse.ArgumentParser(description="balanz. OCPP CSMS or LC with smart charging capabilities")
    parser.add_argument(
        "--config",
        type=str,
        default="config/balanz.ini",
        help="Configuration file (INI format). Default config/balanz.ini",
    )
    args = parser.parse_args()

    # Read config. config object is then available (via config import) to all.
    config.read(args.config)

    # Cheat to use config to share version info and startup-time
    config["balanz"]["version"] = balanz_version
    config["balanz"]["starttime"] = time_str(time.time())

    # Adjust log levels
    for logger_name in config["logging"]:
        logger.warning(f'Setting log level for {logger_name} to {config.get("logging", logger_name)}')
        logging.getLogger(logger_name).setLevel(level=config.get("logging", logger_name))

    # Audit logger
    file_handler = logging.FileHandler(config["history"]["audit_file"])
    file_handler.setFormatter(formatter)
    audit_logger.addHandler(file_handler)

    # Get host config
    host = config.get("host", "addr")
    port = config.get("host", "port")
    cert_chain = config.get("host", "cert_chain", fallback=None)
    cert_key = config.get("host", "cert_key", fallback=None)

    # CSV information
    Group.read_csv(config["model"]["groups_csv"])
    Charger.read_csv(config["model"]["chargers_csv"])
    Tag.read_csv(config["model"]["tags_csv"])
    if config.has_option("history", "session_csv"):
        Session.register_csv_file(config["history"]["session_csv"])
    User.read_csv(config["api"]["users_csv"])

    # Start server, either ws:// or wss://
    if cert_chain and cert_key:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(certfile=cert_chain, keyfile=cert_key)
        server = await websockets.serve(
            on_connect,
            host,
            port,
            subprotocols=["ocpp1.6"],
            process_request=process_request,
            ssl=ssl_context,
            ping_timeout=config.getint("host", "ping_timeout"),
        )
    else:
        server = await websockets.serve(
            on_connect,
            host,
            port,
            subprotocols=["ocpp1.6"],
            process_request=process_request,
            ping_timeout=config.getint("host", "ping_timeout"),
        )

    tasks = []
    # Start Balanz loops (one per allocation group). Only if smart charging enabled
    if config.getint("balanz", "run_interval") == 0:
        logger.info("Not starting balanz smart charging as disabled in configuration")
    else:
        for group in Group.allocation_groups():
            logger.info(f"Started balanz smart charging for allocation group {group.group_id}")
            tasks.append(asyncio.create_task(balanz_loop(group)))

    # Start model watchdog loop
    tasks.append(asyncio.create_task(model_watchdog()))

    # Wait for server to close.   TODO: Should tasks somehow be involved in waiting as well?
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Shutting down server")
        exit(0)
