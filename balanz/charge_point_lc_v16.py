"""
Local Controller (LC) variant of balanz.

It will forward - almost - all messages to a parent Central System server, but listen in
on certain messages in order to provide the Smart Charing functionality. Messages issued
to SmartMetering will not go to the Central System (not even call responses).

In the LC setup, no CP originated calls will be handled fully be the LC. All such
calls will be forwarded to the external server. In some cases, there will be @after
functions that will "listen in on" such calls. This includes boot_notification,
status_notification, start_transaction, stop_transaction, and heartbeat.

All responses will also be forwarded, except for the following exception.
If balanz/smart-charging is enabled, there will be calls originating from the LC.
The function to generate unique ids has been overwritten for this case. It does so
by prepending a fixed text, "LC-", to the generate unique id (a UUID). This allow
the upstream function to intercept those responses in order to handle them locally
(and not forward them to the external server).

All downstream messages (calls/replys/errors) will be forwarded; with one exception.
If balanz/smart-charging is enabled AND the call relates to charging (e.g. clearing
or setting of Charging Profiles), then those calls will be intercepted by the LC
and automatically acknowledged.
"""

import asyncio
import inspect
import json
import logging
import time
import uuid

from charge_point_v16 import ChargePoint_v16
from config import config
from model import Charger
from ocpp.charge_point import camel_to_snake_case
from ocpp.exceptions import OCPPError
from ocpp.messages import MessageType, unpack, validate_payload
from ocpp.routing import after
from ocpp.v16 import call_result
from ocpp.v16.enums import Action
from util import parse_time

logger = logging.getLogger("cp_v16")


class ChargePoint_LC_v16(ChargePoint_v16):
    """Local Controller Charger Point."""

    def __init__(self, server_connection, charger: Charger, *args, **kwargs):
        super().__init__(charger=charger, *args, **kwargs)
        self._server_connection = server_connection

        # Init timing field(s). Used for watchdog functionality
        self._last_cp_update = time.time()
        self._last_server_update = time.time()

        # Set pointer to charger in model
        self.charger: Charger = charger
        self.charger.last_update = time.time()

        # Override IDs generated in LC mode. This will help us to recognize the responses.
        self._unique_id_generator = lambda: "LC-" + str(uuid.uuid4())

    @after(Action.boot_notification)
    def on_boot_notification(
        self, charge_point_vendor: str, charge_point_model: str, **kwargs
    ) -> call_result.BootNotification:
        self.charger.boot_notification(
            charge_point_vendor=charge_point_vendor,
            charge_point_model=charge_point_model,
            **kwargs,
        )

    @after(Action.heartbeat)
    def on_heartbeat(self, **kwargs):
        self.charger.heartbeat()

    @after(Action.meter_values)
    # TODO: This function is actually equal across LC and CSMS. That is not good. Abstract it somehow.
    def on_meter_values(self, **kwargs):
        # TODO: Error handling in case things not 100% as expected.
        meter_value = kwargs["meter_value"][0]
        timestamp = parse_time(meter_value["timestamp"])
        sampled_value = meter_value["sampled_value"]

        def extract_sv(measurand: str, phase: str) -> float:
            for sv in sampled_value:
                if sv["measurand"] == measurand and (
                    (phase and sv["phase"] == phase) or (not phase and "phase" not in sv)
                ):
                    return float(sv["value"])
            return 0

        # Usage will be determine as the maximum Current import across the 3 phases.
        usage_meter = max(
            extract_sv("Current.Import", "L1"),
            extract_sv("Current.Import", "L2"),
            extract_sv("Current.Import", "L3"),
        )
        energy_meter = extract_sv("Energy.Active.Import.Register", None)
        offered = extract_sv("Current.Offered", None)
        self.charger.meter_values(
            connector_id=kwargs["connector_id"],
            transaction_id=kwargs.get("transaction_id", None),
            timestamp=timestamp,
            usage_meter=usage_meter,
            energy_meter=energy_meter,
            offered=offered,
        )

    @after(Action.status_notification)
    def on_status_notification(self, **kwargs):
        self.charger.status_notification(connector_id=kwargs["connector_id"], status=kwargs["status"])

    @after(Action.start_transaction)
    def on_start_transaction(self, **kwargs):
        timestamp = parse_time(kwargs["timestamp"])
        self.charger.start_transaction(
            connector_id=kwargs["connector_id"],
            id_tag=kwargs["id_tag"],
            timestamp=timestamp,
            meter_start=kwargs["meter_start"],
        )

    @after(Action.stop_transaction)
    def on_stop_transaction(self, **kwargs):
        timestamp = parse_time(kwargs["timestamp"])
        reason = kwargs["reason"] if "reason" in kwargs else None
        self.charger.stop_transaction(
            transaction_id=kwargs["transaction_id"],
            stop_id_tag=kwargs["id_tag"],
            timestamp=timestamp,
            meter_stop=kwargs["meter_stop"],
            reason=reason,
        )

    async def start_lc_up(self):
        while True:
            try:
                message = await self._connection.recv()
                logger.debug("%s: lc receive message from cp %s", self.id, message)
                # Set last updated on charger indicating that "there is life"
                self._last_cp_update = self.charger.last_update = time.time()

                forward = await self.route_message(message)
                if forward:
                    await self._server_connection.send(message)
                    logger.debug("... forwarded to server")
            except Exception as e:
                logger.error(f"Exception during start_lc_up: {e}")
                return  # Stop on error

    async def start_lc_down(self):
        while True:
            try:
                message = await self._server_connection.recv()
                logger.debug("%s: lc receive message from server %s", self.id, message)

                # Set last updated on charger indicating that "there is life"
                self._last_server_update = time.time()

                forward = True
                if config.get("ext-server", "server_charging_call") != "Forward":
                    # Need to check message
                    response = await self.route_message_down(message)
                    if response:
                        logger.info(f"Intercepted charging related call. Answering {response}")
                        forward = False  # We will answer directly to CSMS ourselves
                        await self._server_connection.send(response)

                if forward:
                    await self._connection.send(message)
                    logger.debug(".... forwarded to CP")
            except Exception as e:
                logger.error(f"Exception during start_lc_down: {e}")
                return  # Stop on error

    async def watchdog(self):
        """
        Watchdog - LC version

        Watchdog function which will monitor last communication.
        If time since last communication more than a configurable time, close the
        conections and wait for reconnection to occur from CP.
        """
        logging.debug(f"LC watchdog for {self.id} started.")

        while True:
            await asyncio.sleep(config.getint("host", "watchdog_interval"))

            # CP part
            elapsed = time.time() - self._last_cp_update
            if elapsed > config.getint("host", "watchdog_stale"):
                logger.error(f"Watch dog saw no CP activity from {self.id} for {elapsed} seconds. Closing connections")
                return

            # Server part
            elapsed = time.time() - self._last_server_update
            if elapsed > config.getint(
                "host", "watchdog_stale"
            ):  # Using same value as for host, as heartbeats will also propagate
                logger.error(
                    f"Watch dog saw no server activity from {self.id} for {elapsed} seconds. Closing connections"
                )
                return

    # -------------------------------------
    # LC specific versions for routing.
    # -------------------------------------
    # ----------------
    # Downstream LC <- CSMS
    # ----------------
    async def route_message_down(self, raw_msg) -> bool:
        """Route message from CSMS to LC

        Check if message should be intercepted (ClearChargingProfile/SetChargingProfile) and builds the response.

        Returns the response, or None if message will not be intercepted, but should simply be forwarded.
        """
        try:
            msg = unpack(raw_msg)
        except OCPPError as e:
            self.logger.exception("Cannot parse message: '%s', invalid OCPP: %s", raw_msg, e)
            return False

        if msg.message_type_id == MessageType.Call and msg.action in [
            "SetChargingProfile",
            "ClearChargingProfile",
        ]:
            # A bit rough, but ok.
            response = [
                MessageType.CallResult,
                msg.unique_id,
                {"status": config.get("ext-server", "server_charging_call")},
            ]
            return json.dumps(response)

        return None

    # ----------------
    # Upstream  CP->LC
    # ----------------
    async def route_message(self, raw_msg) -> bool:
        """Route a message from a CP to LC

        If the message is a of type Call the corresponding hooks are executed.
        If the message is of type CallResult or CallError the message is passed
        to the call() function via the response_queue.

        Returns True if message should be forwarded to external server. False otherwise
        """
        try:
            msg = unpack(raw_msg)
        except OCPPError as e:
            self.logger.exception("Cannot parse message: '%s', invalid OCPP: %s", raw_msg, e)
            return False

        if msg.message_type_id == MessageType.Call:
            try:
                await self._handle_call(msg)
            except OCPPError as error:
                logger.exception("Error while handling request %s. Error %s", msg, error)
        elif msg.message_type_id in [
            MessageType.CallResult,
            MessageType.CallError,
        ] and msg.unique_id.startswith("LC-"):
            self._response_queue.put_nowait(msg)
            return False

        return True

    async def _handle_call(self, msg):
        """Handle "upstream" call

        Special "upstream version" focusing only on '_after_action' hooks. No responses generated
        """
        if msg.action not in self.route_map:
            # No (on_action in this case) handler defined for call. Nothing for LC to do.
            return
        handlers = self.route_map[msg.action]

        if not handlers.get("_skip_schema_validation", False):
            await validate_payload(msg, self._ocpp_version)

        # OCPP uses camelCase for the keys in the payload. It's more pythonic
        # to use snake_case for keyword arguments. Therefore the keys must be
        # 'translated'. Some examples:
        #
        # * chargePointVendor becomes charge_point_vendor
        # * firmwareVersion becomes firmwareVersion
        snake_case_payload = camel_to_snake_case(msg.payload)

        try:
            handler = handlers["_after_action"]
            handler_signature = inspect.signature(handler)
            call_unique_id_required = "call_unique_id" in handler_signature.parameters
            # call_unique_id should be passed as kwarg only if is defined explicitly
            # in the handler signature
            if call_unique_id_required:
                response = handler(**snake_case_payload, call_unique_id=msg.unique_id)
            else:
                response = handler(**snake_case_payload)
            # Create task to avoid blocking when making a call inside the
            # after handler
            if inspect.isawaitable(response):
                asyncio.ensure_future(response)
        except KeyError:
            # '_on_after' hooks are not required. Therefore ignore exception
            # when no '_on_after' hook is installed.
            pass
        return
