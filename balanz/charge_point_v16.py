"""
Base class for LC and CSMS variant of ChargePoint handling. Do not instantiate this object!
"""

import logging
import time
from datetime import UTC, datetime

from config import config
from model import Charger
from ocpp.v16 import ChargePoint as cp
from ocpp.v16 import call, call_result
from ocpp.v16.datatypes import ChargingProfile
from ocpp.v16.enums import (
    CertificateSignedStatus,
    ChargingProfileKindType,
    ChargingProfilePurposeType,
    ChargingRateUnitType,
    MessageTrigger,
)

logger = logging.getLogger("cp_v16")


# ---------
# Utility
def parse_time(timestamp: str) -> float:
    if len(timestamp) == 0:
        return None
    if timestamp[-1] == "Z":
        timestamp = timestamp[:-1]
    return datetime.fromisoformat(timestamp).timestamp()


class ChargePoint_v16(cp):
    """Base class for ChargePoint.

    Do NOT instantiate!"""

    def __init__(self, charger: Charger, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Init timing field(s). Used for watchdog functionality
        self._last_cp_update = time.time()

        # Set pointer to charger in model
        self.charger: Charger = charger
        self.charger.last_update = time.time()

    def _on_meter_values(self, **kwargs):
        try:
            if "transaction_id" not in kwargs:
                logger.debug("Ignoring meter_values as not in transaction")
            else:
                meter_value = kwargs["meter_value"][0]
                # TODO: timestamp parsing is sometimes off. Set to now
                #                timestamp = parse_time(meter_value["timestamp"])
                timestamp = time.time()
                sampled_value = meter_value["sampled_value"]

                def extract_sv(measurand: str, phase: str, not_found_value=None) -> float:
                    for sv in sampled_value:
                        sv_measurand = sv["measurand"] if "measurand" in sv else "Energy.Active.Import.Register"
                        if sv_measurand == measurand:
                            if (phase and "phase" in sv and sv["phase"] == phase) or (not phase and "phase" not in sv):
                                return float(sv["value"])
                    return not_found_value

                usage_meter = max(
                    extract_sv("Current.Import", "L1", 0),
                    extract_sv("Current.Import", "L2", 0),
                    extract_sv("Current.Import", "L3", 0),
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
        except Exception as e:
            logger.error(f"Exception in _on_meter_values: {e}")

    # -------------------------------------
    # Common call functions
    # -------------------------------------
    async def get_configuration_req(self, **kwargs):
        payload = call.GetConfiguration(**kwargs)
        return await self.call(payload)

    async def change_configuration_req(self, **kwargs):
        payload = call.ChangeConfiguration(**kwargs)
        return await self.call(payload)

    async def clear_cache_req(self, **kwargs):
        payload = call.ClearCache()
        return await self.call(payload)

    async def remote_start_transaction_req(self, **kwargs):
        payload = call.RemoteStartTransaction(**kwargs)
        return await self.call(payload)

    async def remote_stop_transaction_req(self, **kwargs):
        payload = call.RemoteStopTransaction(**kwargs)
        return await self.call(payload)

    async def unlock_connector_req(self, **kwargs):
        payload = call.UnlockConnector(**kwargs)
        return await self.call(payload)

    async def change_availability_req(self, **kwargs):
        payload = call.ChangeAvailability(**kwargs)
        return await self.call(payload)

    async def reset_req(self, **kwargs):
        payload = call.Reset(**kwargs)
        return await self.call(payload)

    async def get_local_list_version_req(self, **kwargs):
        payload = call.GetLocalListVersion()
        return await self.call(payload)

    async def send_local_list_req(self, **kwargs):
        payload = call.SendLocalList(**kwargs)
        return await self.call(payload)

    async def reserve_now_req(self, **kwargs):
        payload = call.ReserveNow(**kwargs)
        return await self.call(payload)

    async def cancel_reservation_req(self, **kwargs):
        payload = call.CancelReservation(**kwargs)
        return await self.call(payload)

    async def trigger_message_req(self, **kwargs):
        payload = call.TriggerMessage(**kwargs)
        return await self.call(payload)

    async def set_charging_profile_req(self, payload: call.SetChargingProfile):
        return await self.call(payload)

    async def get_composite_schedule(self, payload: call.GetCompositeSchedule) -> call_result.GetCompositeSchedule:
        return await self.call(payload)

    async def get_composite_schedule_req(self, **kwargs) -> call_result.GetCompositeSchedule:
        payload = call.GetCompositeSchedule(**kwargs)
        return await self.call(payload)

    async def clear_charging_profile_req(self, **kwargs):
        payload = call.ClearChargingProfile(**kwargs)
        return await self.call(payload)

    async def data_transfer_req(self, **kwargs):
        payload = call.DataTransfer(**kwargs)
        return await self.call(payload)

    async def extended_trigger_message_req(self, **kwargs):
        payload = call.ExtendedTriggerMessage(**kwargs)
        return await self.call(payload)

    async def certificate_signed_req(self, **kwargs):
        payload = call_result.CertificateSigned(CertificateSignedStatus.rejected)
        return await self.call(payload)

    async def install_certificate_req(self, **kwargs):
        payload = call.InstallCertificate(**kwargs)
        return await self.call(payload)

    async def get_installed_certificate_ids_req(self, **kwargs):
        payload = call.GetInstalledCertificateIds(**kwargs)
        return await self.call(payload)

    async def delete_certificate_req(self, **kwargs):
        payload = call.DeleteCertificatePayload(**kwargs)
        return await self.call(payload)

    async def get_log_req(self, **kwargs):
        payload = call.GetLog(**kwargs)
        return await self.call(payload)

    async def signed_update_firmware_req(self, **kwargs):
        payload = call.SignedUpdateFirmware(**kwargs)
        return await self.call(payload)

    async def get_diagnostics_req(self, **kwargs):
        payload = call.GetDiagnostics(**kwargs)
        return await self.call(payload)

    async def update_firmware_req(self, **kwargs):
        payload = call.UpdateFirmware(**kwargs)
        return await self.call(payload)

    # -------------------------------------
    # Smart charging function encapsulation
    # -------------------------------------
    async def clear_all_default_profiles(self):
        """Clear any TxDefaultProfile present. Clearing will default everything, except type profile type/purpose."""
        return await self.clear_charging_profile_req(
            charging_profile_purpose=ChargingProfilePurposeType.tx_default_profile
        )

    async def set_default_profile(
        self,
        charging_profile_id: int,
        connector_id: int,
        stack_level: int,
        limit: float,
    ):
        """Set a TxDefaultProfile with a limit

        Will contain a single schedule.

        This will ensure that charging will not start until capacity is allocated.
        """
        cs_charging_profile = ChargingProfile(
            charging_profile_id=charging_profile_id,
            stack_level=stack_level,
            charging_profile_purpose=ChargingProfilePurposeType.tx_default_profile,
            charging_profile_kind=ChargingProfileKindType.absolute,
            charging_schedule={
                "chargingRateUnit": ChargingRateUnitType.amps,
                "chargingSchedulePeriod": [{"startPeriod": 0, "limit": limit}],
            },
        )

        cs_set_profile = call.SetChargingProfile(connector_id=connector_id, cs_charging_profiles=cs_charging_profile)

        return await self.set_charging_profile_req(cs_set_profile)

    async def set_base_default_profile(self):
        """Set the base default profile

        This profile will allow charging at the minimum rate (if not blocked by blocking profile).

        The profile will be set on connector 0, so applicable for all connectors.
        """
        return await self.set_default_profile(
            charging_profile_id=1,
            connector_id=0,
            stack_level=0,
            limit=config.getint("balanz", "min_allocation"),
        )

    async def set_blocking_default_profile(self, connector_id: int):
        """Set the blocking default profile

        This profile will shadow - and therefore block - the base profile, since it has a higher stack_level.
        """
        return await self.set_default_profile(charging_profile_id=2, connector_id=connector_id, stack_level=1, limit=0)

    async def clear_blocking_default_profile(self, connector_id: int):
        """Clear the blocking default profile

        This allows the base default profile to take effect, and therefore charging to start at the minimum rate.
        """
        return await self.clear_charging_profile_req(id=2, connector_id=connector_id)

    async def set_tx_profile(self, connector_id: int, transaction_id: int, limit: float):
        """Set/overwrite a TxProfile for transaction.

        Will only contain a single schedule (now => forever) with the limit being set to the number of Amps offered.

        Fields like charging_profile_id, stack_level, etc. are all fixed.
        """
        cs_charging_profile = ChargingProfile(
            charging_profile_id=3,
            stack_level=3,
            charging_profile_purpose=ChargingProfilePurposeType.tx_profile,
            charging_profile_kind=ChargingProfileKindType.absolute,
            charging_schedule={
                "chargingRateUnit": ChargingRateUnitType.amps,
                "chargingSchedulePeriod": [{"startPeriod": 0, "limit": limit}],
            },
            transaction_id=transaction_id,
        )

        cs_set_profile = call.SetChargingProfile(connector_id=connector_id, cs_charging_profiles=cs_charging_profile)

        return await self.set_charging_profile_req(cs_set_profile)

    async def trigger_meter_values(self):
        """
        Triggers the meter values to be sent to the charging station.
        """
        return await self.trigger_message_req(requested_message=MessageTrigger.meter_values)

    async def trigger_status_notification(self, connector_id: int):
        """
        Triggers a status notification to be sent to the charging station.
        """
        return await self.trigger_message_req(
            requested_message=MessageTrigger.status_notification, connector_id=connector_id
        )

    async def trigger_boot_notification(self):
        """
        Triggers a boot notification to be sent to the charging station.
        """
        return await self.trigger_message_req(requested_message=MessageTrigger.boot_notification)

    async def update_firmware(self, location: str):
        """
        Triggers a firmware upgrade to be sent to the charging station.
        """
        now_string: str = datetime.now(UTC).isoformat() + "Z"

        await self.update_firmware_req(location=location, retrieve_date=now_string)
