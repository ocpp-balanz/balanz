"""
firmware model. Simple firmware management.

firmware (metadata) will be stored in a CSV file
"""

import csv
import logging
from enum import StrEnum

from config import config

# Logging setup
logger = logging.getLogger("firmware")


# Forward declaration
class Firmware:
    pass


# ---------------------------
# Classes - Implementation
# ---------------------------
class Firmware:
    """
    Firmware represents firmware (metadata)
    """

    # Static dictionary of Sessions. Key is a generated session_id.
    firmware_list: dict[Firmware] = {}

    def __init__(
        self,
        firmware_id: str,
        charge_point_vendor: str,
        charge_point_model: str,
        firmware_version: str,
        meter_type: str,
        url: str,
        upgrade_from_versions: str = None,
    ) -> None:
        """Init"""
        self.firmware_id = firmware_id
        self.charge_point_vendor = charge_point_vendor
        self.charge_point_model = charge_point_model
        self.firmware_version = firmware_version
        self.meter_type = meter_type
        self.url = url
        self.upgrade_from_versions = upgrade_from_versions
        Firmware.firmware_list[firmware_id] = self

    def update(
        self,
        charge_point_vendor: str = None,
        charge_point_model: str = None,
        firmware_version: str = None,
        meter_type: str = None,
        url: str = None,
        upgrade_from_versions: str = None,
    ) -> None:
        if charge_point_vendor is not None:
            self.charge_point_vendor = charge_point_vendor
        if charge_point_model is not None:
            self.charge_point_model = charge_point_model
        if firmware_version is not None:
            self.firmware_version = firmware_version
        if meter_type is not None:
            self.meter_type = meter_type
        if url is not None:
            self.url = url
        if upgrade_from_versions is not None:
            self.upgrade_from_versions = upgrade_from_versions

    def external(self) -> str:
        fields = [
            "firmware_id",
            "charge_point_vendor",
            "charge_point_model",
            "firmware_version",
            "meter_type",
            "url",
            "upgrade_from_versions",
        ]
        result = {k: self.__dict__[k] for k in fields}
        return result

    @staticmethod
    def read_csv(file: str) -> None:
        """Read firmwares from CSV file

        If called again, will only add new firmwares.

        Assumed format: "firmware_id", "charge_point_vendor", "charge_point_model", "firmware_version", "meter_type", "url", "upgrade_from_versions"

        """
        logger.info(f"Reading firmware definitions from {file}")
        try:
            with open(file, mode="r") as file:
                reader = csv.DictReader(file)
                for firmware in reader:
                    print(firmware)
                    if firmware["firmware_id"] not in Firmware.firmware_list:
                        Firmware(
                            firmware_id=firmware["firmware_id"],
                            charge_point_vendor=firmware["charge_point_vendor"],
                            charge_point_model=firmware["charge_point_model"],
                            firmware_version=firmware["firmware_version"],
                            meter_type=firmware["meter_type"],
                            url=firmware["url"],
                            upgrade_from_versions=firmware["upgrade_from_versions"],
                        )
        except FileNotFoundError as e:
            logger.warning(f"File not found {e}. Creating it.")
            Firmware.write_csv(file)
        except csv.Error as e:
            logger.error(e)

    @staticmethod
    def write_csv(file: str) -> None:
        """Rewrite firmware definitions to CSV file to reflect changes"""
        logger.info(f"Writing firmware definitions to {file}")
        with open(file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "firmware_id",
                    "charge_point_vendor",
                    "charge_point_model",
                    "firmware_version",
                    "meter_type",
                    "url",
                    "upgrade_from_versions",
                ]
            )
            firmware: Firmware = None
            for u in Firmware.firmware_list:
                firmware = Firmware.firmware_list[u]
                writer.writerow(
                    [
                        firmware.firmware_id,
                        firmware.charge_point_vendor,
                        firmware.charge_point_model,
                        firmware.firmware_version,
                        firmware.meter_type,
                        firmware.url,
                        firmware.upgrade_from_versions,
                    ]
                )
