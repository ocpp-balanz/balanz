"""
Central System variant of balanz.

It will handle the most important messages from a CP, and default to "playing along"
for the rest.
"""

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone

from charge_point_v16 import ChargePoint_v16
from config import config
from model import Charger
from ocpp.routing import on
from ocpp.v16 import call, call_result
from ocpp.v16.datatypes import IdTagInfo
from ocpp.v16.enums import (
    Action,
    AuthorizationStatus,
    ConfigurationStatus,
    DataTransferStatus,
    GenericStatus,
    RegistrationStatus,
)
from util import gen_sha_256, parse_time

logger = logging.getLogger("cp_v16")


class ChargePoint_CSMS_v16(ChargePoint_v16):
    """Central System handling of a ChargerPoint"""

    def __init__(self, charger: Charger, *args, **kwargs):
        super().__init__(charger=charger, *args, **kwargs)

        # Init timing field(s). Used for watchdog functionality
        self._last_cp_update = time.time()

        # Set pointer to charger in model
        self.charger: Charger = charger
        self.charger.last_update = time.time()

    @on(Action.boot_notification)
    def on_boot_notification(
        self, charge_point_vendor: str, charge_point_model: str, **kwargs
    ) -> call_result.BootNotification:
        self.charger.boot_notification(
            charge_point_vendor=charge_point_vendor,
            charge_point_model=charge_point_model,
            **kwargs,
        )

        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=config.getint("csms", "heartbeat_interval"),
            status=RegistrationStatus.accepted,
        )

    @on(Action.heartbeat)
    def on_heartbeat(self, **kwargs):
        self.charger.heartbeat()
        return call_result.Heartbeat(current_time=datetime.now(timezone.utc).isoformat())

    @on(Action.authorize)
    def on_authorize(self, **kwargs):
        id_tag_info: IdTagInfo = self.charger.authorize(kwargs["id_tag"])
        return call_result.Authorize(id_tag_info=id_tag_info)

    @on(Action.meter_values)
    def on_meter_values(self, **kwargs):
        # Really not nice that this is replicated with LC...
        if "transaction_id" not in kwargs:
            logger.debug("Ignoring meter_values as not in transaction")
        else:
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

            usage_meter = max(
                extract_sv("Current.Import", "L1"),
                extract_sv("Current.Import", "L2"),
                extract_sv("Current.Import", "L3"),
            )
            energy_meter = extract_sv("Energy.Active.Import.Register", None)
            offered = extract_sv("Current.Offered", None)
            self.charger.meter_values(
                connector_id=kwargs["connector_id"],
                transaction_id=kwargs["transaction_id"],
                timestamp=timestamp,
                usage_meter=usage_meter,
                energy_meter=energy_meter,
                offered=offered,
            )
        return call_result.MeterValues()

    @on(Action.status_notification)
    def on_status_notification(self, **kwargs):
        self.charger.status_notification(connector_id=kwargs["connector_id"], status=kwargs["status"])
        return call_result.StatusNotification()

    @on(Action.start_transaction)
    def on_start_transaction(self, **kwargs):
        timestamp = parse_time(kwargs["timestamp"])
        self.charger.start_transaction(
            connector_id=kwargs["connector_id"],
            id_tag=kwargs["id_tag"],
            timestamp=timestamp,
            meter_start=kwargs["meter_start"],
        )
        # Todo, authorized sometimes?
        id_tag_info = IdTagInfo(status=AuthorizationStatus.accepted)
        return call_result.StartTransaction(transaction_id=1, id_tag_info=id_tag_info)

    @on(Action.stop_transaction)
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
        return call_result.StopTransaction()

    @on(Action.diagnostics_status_notification)
    def on_diagnostics_status_notification(self, **kwargs):
        return call_result.DiagnosticsStatusNotification()

    @on(Action.sign_certificate)
    def on_sign_certificate(self, **kwargs):
        self.csr = kwargs["csr"]
        return call_result.SignCertificate(GenericStatus.accepted)

    @on(Action.security_event_notification)
    def on_security_event_notification(self, **kwargs):
        return call_result.SecurityEventNotification()

    @on(Action.signed_firmware_status_notification)
    def on_signed_update_firmware_status_notificaion(self, **kwargs):
        return call_result.SignedFirmwareStatusNotification()

    @on(Action.log_status_notification)
    def on_log_status_notification(self, **kwargs):
        return call_result.LogStatusNotification()

    @on(Action.firmware_status_notification)
    def on_firmware_status_notification(self, **kwargs):
        return call_result.FirmwareStatusNotification()

    @on(Action.data_transfer)
    def on_data_transfer(self, **kwargs):
        call.DataTransferPayload(**kwargs)
        return call_result.DataTransfer(status=DataTransferStatus.rejected, data="Not supported")

    # -------------------------------------
    # start/loop/watchdog functions. CSMS versions
    # -------------------------------------
    async def start(self):
        """start the charger processing loop"""
        while True:
            message = await self._connection.recv()
            self.logger.info("%s: receive message %s", self.id, message)

            # Update timestamps, both on this object and charger object in model (so logic can see it
            # even after this object may go away after e.g. a watchdog initiated close).
            self._last_cp_update = self.charger.last_update = time.time()

            await self.route_message(message)

    async def watchdog(self):
        """Watchdog

        Watchdog function which will monitor last communication.
        If time since last communication more than a configurable time, close the
        conection and wait for reconnection to occur from CP.
        """
        logging.debug(f"CSMS Watchdog for {self.id} started.")

        while True:
            await asyncio.sleep(config.getint("host", "watchdog_interval"))

            elapsed = time.time() - self._last_cp_update
            if elapsed > config.getint("host", "watchdog_stale"):
                logger.error(f"Watch dog saw no CP activity from {self.id} for {elapsed} seconds. Closing connection")
                return

    async def set_new_authorizationkey(self) -> None:
        """Set new AuthorizationKey for the charger."""
        await asyncio.sleep(config.getint("host", "http_auth_delay"))

        authorizationKey = Charger.gen_auth()

        result = await self.change_configuration_req(key="AuthorizationKey", value=authorizationKey)
        auth_string = self.charger.charger_id + ":" + authorizationKey
        auth_string_b64 = base64.b64encode(auth_string.encode()).decode()
        self.charger.auth_sha = gen_sha_256("Basic " + auth_string_b64)
        logger.info(f"Succesfully set AuthorizationKey for {self.charger.charger_id}. Sha is {self.charger.auth_sha}")

        # Rewriting CSV file. Maybe not super-pretty. Must review if better place to do this.
        Charger.write_csv(config["model"]["chargers_csv"])
