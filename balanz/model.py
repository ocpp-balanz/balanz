"""
Balanz model.

OCPP-based modelling to support smart-charging rebalancing across groups of chargers (Balanz).

Groups are used to group chargers, allowing the all-important specification of maximum allocation.

Chargers with 1 or more Connectors make up the charging infrastructure. They will be
associated with a group.

When Connectors are engaged in a charging transaction, a Transaction will represent this. After
the charging is complete, a Session object will be created to capture it's history.
Whenever charging allocation/offers changes over the course of a transaction, it will be will be
recorded as ChargingHistory on a Transaction. This history will also be part of the subsequent
historic charging session.

Finally, the model allows to include Tags (cards) in order to validate Authorize requests.

Main classes, Group, Charger, Tag, Session each include a static list of all such instances.
The __init__ constructors automatically insert instances into such lists. E.g Group.group_list.

The main logic resides in the 'balanz' function to be called on a Group which has a max_allocation
value set.
"""

import csv
import logging
import random
import string
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import ceil

from config import config
from ocpp.v16.datatypes import IdTagInfo
from ocpp.v16.enums import AuthorizationStatus, ChargePointStatus
from util import (
    adjust_time_top_of_hour,
    duration_str,
    kwh_str,
    max_priority_allocation,
    schedule_value_now,
    status_in_transaction,
    time_str,
)

# Logging setup
logger = logging.getLogger("model")


# ---------------------------
# Utility functions (local)
# ---------------------------
# CSV support. Returns a string, or None if blank
def _sn(val):
    return val if val != "" else None


# CSV support. Returns integer, or None if blank
def _in(val):
    return int(val) if val != "" else None


# CSV support. Returns float, or None if blank
def _fn(val):
    return float(val) if val != "" else None


# CSV support. Returns blank string if None, else value
def _sb(val):
    return val if val is not None else ""


# ------------------------------------------------------
# Notes on timestamps. Uses float (seconds since Epoch). In UTC (matches OCPP usage)


# Represents a ChargeChange as returned in lists from the main balanz function.
@dataclass
class ChargeChange:
    charger_id: str
    connector_id: int
    transaction_id: int
    allocation: float  # In Amps


@dataclass
class ChargingHistory:
    timestamp: float
    offered: float

    def external(self) -> str:
        return {"timestamp": self.timestamp, "offered": self.offered}


class TagStatusType(StrEnum):
    """Tag status types."""

    activated = "Activated"
    blocked = "Blocked"


# ---------------------------
# Exceptions
# ---------------------------
@dataclass
class ModelException(Exception):
    value: str


# ---------------------------
# Classes - Forward declarations
# ---------------------------
class Transaction:
    pass


class Session:
    pass


class Connector:
    pass


class Charger:
    pass


class Group:
    pass


class Tag:
    pass


# ---------------------------
# Classes - Implementation
# ---------------------------
class Session:
    """
    Session represents a completed transaction, maintained for historic purposes.

    The Session will be represented by a generated session_id and inserted into a global session_list.

    The constructor will be called as a result of terminating a Transaction (typically as a result of a
    stop_transaction call).

    If history function is enabled, the completed session will be appended to a specified .CSV file for
    subsequent external analysis.
    """

    # Static dictionary of Sessions. Key is a generated session_id.
    session_list: dict[Session] = {}

    # CSV Writer
    session_writer: csv.writer = None

    def __init__(
        self,
        trans: Transaction,
        meter_stop: int,
        timestamp: float,
        reason: str = None,
        stop_id_tag: str = None,
    ) -> None:
        # Copy relevant fields from Transaction
        self.charger_id: str = trans.charger_id
        self.charger_alias: str = Charger.charger_list[self.charger_id].alias
        self.group_id: str = Charger.charger_list[self.charger_id].group_id
        self.connector_id: int = trans.connector_id
        self.id_tag: str = trans.id_tag
        self.user_name: str = trans.user_name

        self.meter_start: float = trans.meter_start
        self.start_time: float = trans.start_time
        self.user_name: str = trans.user_name
        self.charging_history: list[ChargingHistory] = trans.charging_history

        # Remaining fields (arguments or calculated)
        self.meter_stop = meter_stop
        self.end_time = round(timestamp, 2)
        self.stop_id_tag = stop_id_tag
        self.reason = reason
        self.duration: float = self.end_time - self.start_time
        self.energy_meter: float = self.meter_stop - self.meter_start

        # Generate a charging session id to be associated with the transaction.
        # This will be used later for storing the charging session data.
        self.session_id: str = (
            self.charger_id + "-" + datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d-%H:%M:%S")
        )

        # Insert to the charging session list
        Session.session_list[self.session_id] = self

        # Write to CSV file if registered
        if Session.session_writer:
            history = ""
            if self.charging_history:
                history = ";".join([f"{time_str(ch.timestamp)}={ch.offered}A" for ch in self.charging_history])
            Session.session_writer.writerow(
                [
                    self.session_id,
                    self.charger_id,
                    self.charger_alias,
                    self.group_id,
                    self.id_tag,
                    self.user_name,
                    self.stop_id_tag,
                    time_str(self.start_time),
                    time_str(self.end_time),
                    duration_str(self.duration),
                    kwh_str(self.energy_meter),
                    self.reason,
                    history,
                ]
            )
        logger.info(f"Created session {self.session_id} for connector {self.charger_id}/{self.connector_id}")

    def external(self) -> str:
        fields = [
            "session_id",
            "charger_id",
            "charger_alias",
            "group_id",
            "id_tag",
            "user_name",
            "stop_id_tag",
            "start_time",
            "end_time",
            "duration",
            "energy_meter",
            "reason",
        ]
        result = {k: self.__dict__[k] for k in fields}
        result["kwh"] = kwh_str(self.energy_meter)
        result["charging_history"] = [ch.external() for ch in self.charging_history]
        return result

    @staticmethod
    def register_csv_file(filename: str) -> None:
        """Check that file may be open and read"""
        try:
            file = open(filename, "r")
            file.close()
        except:
            # Can't open. Create, write header, and close
            file = open(filename, "w", newline="")
            writer: csv.writer = csv.writer(file)
            writer.writerow(
                [
                    "session_id",
                    "charger_id",
                    "charger_alias",
                    "group_id",
                    "id_tag",
                    "user_name",
                    "stop_id_tag",
                    "start_time",
                    "end_time",
                    "duration",
                    "energy",
                    "stop_reason",
                    "history",
                ]
            )
            file.close()
        file = open(filename, "a+", newline="", buffering=1)
        Session.session_writer = csv.writer(file)
        logger.info(f"Appending completed sessions to {filename}")

    def __str__(self) -> str:
        return str(vars(self))


class Transaction:
    """A transaction represents an active charging session."""

    def __init__(
        self,
        transaction_id: int,
        charger_id: str,
        connector: Connector,
        id_tag: str,
        start_time: float,
        meter_start: int,
    ) -> None:
        self.transaction_id = transaction_id
        self.charger_id = charger_id
        self.connector_id = connector.connector_id
        self.connector: Connector = connector
        self.id_tag = id_tag
        self.start_time = start_time
        self.meter_start = meter_start  # Wh (Watt hours)

        # Lookup the id_tag and try to find a user_name
        self.user_name: str = Tag.tag_list[id_tag].user_name if id_tag in Tag.tag_list else "Unknown"

        # Accessible fields
        self.usage_meter: float = None  # Last usage in A as reported by the charger.
        self.energy_meter: int = meter_start  # In Wh (Watt hours). Will be updated by MeterValues messages.
        self.last_usage_time: float = start_time
        self.charging_history: list[ChargingHistory] = []

        # If tag is known, check if it has a priority.
        if id_tag in Tag.tag_list and Tag.tag_list[id_tag].priority is not None:
            self.priority = Tag.tag_list[id_tag].priority
            logger.debug(f"Transaction priority set to {self.priority} from tag {id_tag}")
        else:
            self.priority: int = None

        # Reset balanz helper fields
        self.connector._bz_reset()
        self.connector._bz_last_offer_time = time.time()
        self.connector._bz_blocking_profile_reset = False

        logger.info(
            f"Created transaction {transaction_id} for connector {charger_id}/{self.connector_id} by tag {id_tag}"
            f" starting at {time_str(start_time)}"
        )

    def external(self) -> str:
        fields = ["id_tag", "start_time", "meter_start", "user_name", "usage_meter", "energy_meter"]
        result = {k: self.__dict__[k] for k in fields}
        result["charging_history"] = [ch.external() for ch in self.charging_history]
        return result

    def __str__(self) -> str:
        return str(vars(self))

    def id_str(self) -> str:
        return f"{self.charger_id}/{self.connector_id}:{self.transaction_id}"


class Connector:
    """A connector represents a physical connector on a charger.

    When in an operating state, it will have an associated transaction.
    When no transaction, i.e. not in an operating state, we will assume no allocation (offered) nor usage!

    Functions to update is done via the Charger.
    """

    def __init__(self, charger: Charger, connector_id: int) -> None:
        self.charger_id = charger.charger_id
        self.charger: Charger = charger
        self.connector_id = connector_id

        # Accessible fields
        self.transaction_id: int = None
        self.status: str = None  # Initial state until set.
        self.transaction: Transaction = None  # Points to transaction object if in operation state
        self.offered: float = None  # A

        # Internal fields for Balanz algorithm.
        self._bz_allocation: float = None
        self._bz_done: bool = False
        self._bz_to_review: bool = False
        self._bz_max: float

        # Balanz helper fields (will be reset upon transaction start)
        self._bz_ev_max_usage: float = None  # Do not exceed this value when charging for the rest of the transaction
        self._bz_suspend_until: float = (
            None  # Suspend offering until this time (used to retry for e.g. delayed charging)
        )
        self._bz_blocking_profile_reset: bool = (
            True  # Flag to indicate if the blocking profile has been reset. Should be done with first TxProfile change,
            # OR if entering a non-transaction state
        )
        # Last time an offer (which will be always @/above the minimum was made).
        # It is implicit at start (otherwise Transaction would not have started)
        self._bz_last_offer_time: float = None
        self._bz_recent_usages: deque[(float, float)] = (
            deque()
        )  # Queue of (usage, time) pairs to calculate recent usage (used for balancing)

    def _bz_reset(self) -> None:
        """Reset various bz fields"""
        logger.debug(f"Resetting connector fields for {self.id_str()}")
        self._bz_ev_max_usage = None
        self._bz_suspend_until = None
        self._bz_last_offer_time = None
        self._bz_recent_usages.clear()

    def external(self) -> str:
        fields = ["transaction_id", "offered"]
        result = {k: self.__dict__[k] for k in fields}
        result["status"] = str(self.status)
        result["priority"] = self.conn_priority()
        result["ev_max_usage"] = self._bz_ev_max_usage
        result["suspend_until"] = self._bz_suspend_until
        if self.transaction:
            result["transaction"] = self.transaction.external()
        return result

    def update_recent_usage(self, usage: float, timestamp: float) -> None:
        """Update the usage of this transaction."""
        self._bz_recent_usages.append((usage, timestamp))
        self.expire_recent_usage()

    def expire_recent_usage(self) -> None:
        """Expire recent usage older than configured interval minutes."""
        now = time.time()
        self._bz_recent_usages = deque(
            filter(
                lambda x: now - x[1] < config.getint("balanz", "usage_monitoring_interval"),
                self._bz_recent_usages,
            )
        )

    def get_max_recent_usage(self) -> float:
        """Get the maximum recent usage."""
        self.expire_recent_usage()
        if not self._bz_recent_usages:
            return 0.0
        max_usage, _ = max(self._bz_recent_usages)
        return max_usage

    def __str__(self) -> str:
        return str(vars(self))

    def id_str(self) -> str:
        return f"{self.charger_id}/{self.connector_id}"

    def conn_max(self) -> float:
        return self.charger.conn_max

    def conn_priority(self) -> int:
        # Priority may have been overwritten at transaction level
        if self.transaction and self.transaction.priority is not None:
            return self.transaction.priority
        else:
            return self.charger.priority


class Charger:
    """
    A charger represents a physical charger. It has a number of connectors.
    """

    # Static Dictionary of Chargers. Key is charger_id. Value is a Charger object.
    charger_list: dict[Charger] = {}

    def __init__(
        self,
        charger_id: str,
        group_id: str,
        alias: str,
        no_connectors: int = 1,
        priority: int = 1,
        description: str = None,
        conn_max: int = None,
        auth_sha: str = None,
    ) -> None:
        """
        constructor

        :raises:
        ModelException: If trying to be bad, e.g. by ref unknown group
        """

        # DB Fields
        self.charger_id = charger_id
        self.alias = alias
        if group_id not in Group.group_list:
            logger.error(f"Group {group_id} not found")
            raise ModelException(f"Group {group_id} not found")
        self.group_id = group_id
        self.priority = priority
        # Insert charger into group list of chargers
        Group.group_list[group_id].chargers[self.charger_id] = self  #
        self.description = description
        self.conn_max = conn_max if conn_max is not None else config.getfloat("balanz", "default_max_allocation")
        self.auth_sha = auth_sha
        self.ocpp_ref = None  # Reference - when connected - used to communicate with charger

        # Fields to come from boot_notification
        self.charge_point_model: str = None
        self.charge_point_vendor: str = None
        self.charge_box_serial_number: str = None
        self.charge_point_serial_number: str = None
        self.firmware_version: str = None
        self.meter_type: str = None

        # Technically there is a Connector 0 representing the charger as well. This will not be used.
        self.connectors: dict[Connector] = {}
        for connector_id in range(1, 1 + no_connectors):  # 1-based
            self.connectors[connector_id] = Connector(charger=self, connector_id=connector_id)

        # Maintain timestamp when last heard from Charger
        self.last_update: float = None

        # Flag to denote if should set the default profile (to 0). Will be handled as part of balanz
        self.profile_initialized: bool = False
        self.requested_status: bool = False

        # Insert to the charger list
        Charger.charger_list[charger_id] = self
        logger.debug(f"Created charger {charger_id} with alias {alias} in group {group_id}")

    def update(self, alias: str = None, priority: int = None, description: str = None, conn_max: int = None) -> None:
        """Update specified field on existing charger"""
        if alias:
            self.alias = alias
        if priority:
            self.priority = priority
        if description:
            self.description = description
        if conn_max:
            self.conn_max = conn_max

    def external(self) -> str:
        # Hint: See all with [k for k in c.__dict__]
        fields = [
            "charger_id",
            "alias",
            "group_id",
            "priority",
            "description",
            "conn_max",
            "charge_point_model",
            "charge_point_vendor",
            "charge_box_serial_number",
            "charge_point_serial_number",
            "firmware_version",
            "meter_type",
        ]
        result = {k: self.__dict__[k] for k in fields}
        result["connectors"] = {conn_id: self.connectors[conn_id].external() for conn_id in self.connectors.keys()}
        result["network_connected"] = self.ocpp_ref is not None
        return result

    @staticmethod
    def read_csv(file: str) -> None:
        """Read chargers from CSV file

        Can be called again. If so will update (if changed) alias, priority, description, conn_max, and auth_sha

        TODO: Delete case, i.e. if existing charger not mentioned in CSV file.

        Assumed format: "charger_id","alias","group_id","no_connectors","priority","description","conn_max","auth_sha"
        """
        logger.info(f"Reading chargers from {file}")
        with open(file, mode="r") as file:
            reader = csv.DictReader(file)
            for charger in reader:
                if charger["charger_id"] in Charger.charger_list:
                    # Update case
                    c: Charger = Charger.charger_list[charger["charger_id"]]
                    c.alias = charger["alias"]
                    c.priority = _in(charger["priority"])
                    c.description = charger["description"]
                    c.conn_max = _fn(charger["conn_max"])
                    c.auth_sha = _sn(charger["auth_sha"])
                    logger.debug(f"Updated charger {c.charger_id}")
                else:
                    # Create case.
                    Charger(
                        charger_id=charger["charger_id"],
                        alias=charger["alias"],
                        group_id=_sn(charger["group_id"]),
                        no_connectors=_in(charger["no_connectors"]),
                        priority=_in(charger["priority"]),
                        description=charger["description"],
                        conn_max=_fn(charger["conn_max"]),
                        auth_sha=_sn(charger["auth_sha"]),
                    )

    @staticmethod
    def write_csv(file: str) -> None:
        """Rewrite chargers to CSV file to reflect changes, i.e. auth_sha set"""
        logger.info(f"Writing chargers to {file}")
        with open(file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "charger_id",
                    "alias",
                    "group_id",
                    "no_connectors",
                    "priority",
                    "description",
                    "conn_max",
                    "auth_sha",
                ]
            )
            charger: Charger = None
            for c in Charger.charger_list:
                charger = Charger.charger_list[c]
                writer.writerow(
                    [
                        charger.charger_id,
                        charger.alias,
                        charger.group_id,
                        len(charger.connectors),
                        charger.priority,
                        charger.description,
                        _sb(charger.conn_max),
                        _sb(charger.auth_sha),
                    ]
                )

    @staticmethod
    def gen_auth() -> str:
        """Generate a new AuthorizationKey value. 16 bytes"""
        chars = string.ascii_letters + string.digits + string.punctuation
        key = "".join(random.choice(chars) for _ in range(16))
        return key

    def remove(self) -> None:
        """Remove Charger from model. Does not work with __del__"""
        Charger.charger_list.pop(self.charger_id)
        Group.group_list[self.group_id].chargers.pop(self.charger_id)

    def __str__(self) -> str:
        return str(vars(self))

    def is_in_group(self, group_id) -> bool:
        """Check if Charger is in specific group_id"""
        return self.group_id == group_id

    def offered(self) -> float:
        """Sum of offered from all connector transactions"""
        return sum(connector.offered for connector in self.connectors.values() if connector.offered is not None)

    def usage(self) -> float:
        """Sum of usage from all connectors w/ active transactions"""
        return sum(
            connector.transaction.usage_meter
            for connector in self.connectors.values()
            if connector.transaction and connector.transaction.usage_meter
        )

    def energy(self) -> float:
        """Sum of energy from all connectors w/ active transactions"""
        return sum(
            connector.transaction.energy_meter
            for connector in self.connectors.values()
            if connector.transaction and connector.transaction.energy_meter
        )

    def charge_change_implemented(self, charge_change: ChargeChange) -> None:
        """Report back that a requested ChargeChange has been done, allowing the fields to be updated in the model."""
        connector: Connector = Charger.charger_list[charge_change.charger_id].connectors[charge_change.connector_id]
        connector.offered = charge_change.allocation
        if charge_change.allocation >= config.getfloat("balanz", "min_allocation"):
            # Update to reflect a new allocation.
            connector._bz_last_offer_time = time.time()  # Update last offer time to now
            connector._bz_recent_usages.clear()  # Reset monitoring
            connector._bz_suspend_until = None

        # Charging history
        if connector.transaction is not None:
            connector.transaction.charging_history.append(
                ChargingHistory(timestamp=time.time(), offered=connector.offered)
            )
        logger.debug(f"Charge change done {charge_change}.")

    def boot_notification(self, charge_point_model: str, charge_point_vendor: str, **kwargs) -> None:
        """Simply update the fields."""
        self.charge_point_model = charge_point_model
        self.charge_point_vendor = charge_point_vendor

        # The dynamic parts. Copy any attributes from kwargs onto the charger.
        for arg in kwargs:
            if hasattr(self, arg):
                setattr(self, arg, kwargs[arg])
        logger.info(f"boot_notification from {self.charger_id}")

    def heartbeat(self, timestamp: float = None) -> None:
        """Register a Heartbeat for the charger. Updates the last_update field."""
        if not timestamp:
            timestamp = time.time()
        logger.debug(f"heartbeat from {self.charger_id}")

    def authorize(self, id_tag: str) -> IdTagInfo:
        """Authorize a tag.

        Returns True if tag accepted. Second parameter is the optional parent_id_tag (can be None)
        """
        id_tag = id_tag.upper()
        logger.debug(f"authorize. Checking tag {id_tag}")
        if id_tag not in Tag.tag_list:
            logger.warning("authorize. Rejecting as tag not found")
            return IdTagInfo(status=AuthorizationStatus.invalid)
        else:
            tag: Tag = Tag.tag_list[id_tag]
            if tag.status == TagStatusType.activated:

                if not config.getboolean("csms", "allow_concurrent_tag"):
                    running_id_tags = [
                        conn.transaction.id_tag
                        for c in Charger.charger_list.values()
                        for conn in c.connectors.values()
                        if conn.transaction is not None and c != self
                    ]
                    logger.debug(f"running_id_tags: {running_id_tags}")
                    if id_tag in running_id_tags:
                        logger.info("authorize. Rejecting as tag already used in another transaction.")
                        return IdTagInfo(status=AuthorizationStatus.concurrent_tx)

                logger.info(f"authorize. Accepting tag {tag.id_tag}. Parent_id is {tag.parent_id_tag}")
                return IdTagInfo(status=AuthorizationStatus.accepted, parent_id_tag=tag.parent_id_tag)
            else:
                logger.warning(f"authorize. Rejecting tag {tag.id_tag} as in state {tag.status}")
                return IdTagInfo(status=AuthorizationStatus.blocked)

    def start_transaction(self, connector_id: int, id_tag: str, meter_start: int, timestamp: float) -> int:
        """Start a transaction on the connector. Returns the transaction id."""
        if connector_id not in self.connectors:
            e = f"[start_transaction Connector {self.charger_id}/{connector_id} not found"
            logger.error(e)
            raise ModelException(e)

        connector: Connector = self.connectors[connector_id]
        if connector.transaction is not None:
            logger.warning(
                f"start_transaction: Connector {self.charger_id}/{connector.connector_id} already in transaction"
                f" {connector.transaction.transaction_id}."
            )
            # Hmm. Is this the same transaction, or a new transaction?
            if connector.transaction.start_time == timestamp:
                # Seems likely that it is the same..
                logger.warning("start_transaction: Assuming this is the same as timestamps match")
                return connector.transaction_id
            else:
                logger.warning("start_transaction: Stopping old transaction before starting new")
                self.stop_transaction(
                    transaction_id=connector.transaction.transaction_id,
                    meter_stop=connector.transaction.energy_meter,
                    timestamp=timestamp,
                    reason="Start transaction without stop transaction",
                )

        # Do the new transaction
        connector.transaction_id = connector_id  # So, mostly will be 1 (if there is only one connector).
        connector.transaction = Transaction(
            transaction_id=connector.transaction_id,
            charger_id=self.charger_id,
            connector=connector,
            id_tag=id_tag,
            start_time=timestamp,
            meter_start=meter_start,
        )
        logger.info(
            f"start_transaction: Connector {self.charger_id}/{connector_id} started transaction "
            f"{connector.transaction_id} with id tag {id_tag} and meter start {meter_start}"
        )

        # Flag for quick balanz() review
        connector._bz_to_review = True

        # Reset stuff.
        connector._bz_reviewed = False
        return connector.transaction_id

    def stop_transaction(
        self,
        transaction_id: int,
        meter_stop: int,
        timestamp: float,
        reason: str = None,
        stop_id_tag: str = None,
    ) -> str:
        """Stop a transaction on the connector. Returns the charging session id."""
        # Find the connector
        search_id = [
            c
            for c in self.connectors
            if self.connectors[c].transaction is not None
            and self.connectors[c].transaction.transaction_id == transaction_id
        ]
        if len(search_id) == 0:
            e = f"stop_transaction. Transaction Id {transaction_id} not found on {self.charger_id}"
            logger.error(e)
            return None
        connector_id = search_id[0]  # TODO. Could be nicer.
        connector = self.connectors[connector_id]

        # Make a final historic entry
        connector.transaction.charging_history.append(ChargingHistory(timestamp=timestamp, offered=0))

        # Make Session object
        session = Session(
            connector.transaction,
            meter_stop=meter_stop,
            timestamp=timestamp,
            stop_id_tag=stop_id_tag,
            reason=reason,
        )

        # Loose transaction
        del connector.transaction
        connector.transaction = None
        connector.transaction_id = None
        connector._bz_reviewed = False  # Reset flag for later
        connector._bz_reset()

        logger.info(
            f"stop_transaction: Connector {self.charger_id}/{connector.connector_id} stopped."
            f" id_tag: {stop_id_tag}, reason: {reason}"
        )

        return session.session_id

    def status_notification(self, connector_id: int, status: ChargePointStatus) -> None:
        """Update the status of the connector. Will also update the last_update field."""
        if connector_id == 0:
            logger.debug(f"Ignoring status notification for connector {self.charger_id}/0: {status}")
            return
        if connector_id not in self.connectors:
            e = f"status_notification: Connector {self.charger_id}/{connector_id} not found"
            logger.error(e)
            raise ModelException(e)

        connector: Connector = self.connectors[connector_id]
        old_status = connector.status
        if status != old_status:
            logger.info(
                f"Updating status for connector {self.charger_id}/{connector.connector_id}:"
                f" {connector.status} => {status}"
            )
            connector.status = status

            # ------------
            # balanz() related logic

            # Flag a potential start charging case for balanz to review
            if connector.transaction is None and status == ChargePointStatus.suspended_evse:
                connector._bz_to_review = True

            # If status is SuspendedEV, then clearly usage in transaction will be zero
            if status == ChargePointStatus.suspended_ev:
                connector.update_recent_usage(0.0, time.time())
                if connector.transaction is not None:
                    connector.transaction.usage_meter = 0.0

        # If new status is clearly out of transaction, assume charging profile logic is correct
        # and so nothing is offered
        if not status_in_transaction(status):
            connector.offered = 0
            connector._bz_reset()

    def meter_values(
        self,
        connector_id: int,
        usage_meter: float,
        energy_meter: int,
        timestamp: float,
        offered: float = None,
        transaction_id: int = None,
    ) -> None:
        """Update the meter values for the connector. Will also update the last_update field.

        usage_meter is assumed to represent the current usage (in A).
        This could be done by taking the maximum of Current.Import for all phases.
        """
        if connector_id not in self.connectors:
            e = f"[meter_values: Connector {self.charger_id}/{connector_id} not found"
            logger.warning(e)
            return

        connector: Connector = self.connectors[connector_id]
        if transaction_id is not None:
            if not connector.transaction:
                # This is likely a startup situation.
                logger.warning(
                    f"[meter_values: Connector {self.charger_id}/{connector.connector_id} not in transaction."
                    f" Synthezing transaction with id {transaction_id}"
                )
                connector.transaction = Transaction(
                    transaction_id=transaction_id,
                    charger_id=self.charger_id,
                    connector=connector,
                    id_tag="Unknown",
                    start_time=time.time(),
                    meter_start=0,
                )
                # Have an opinion about connector status..
                if not status_in_transaction(connector.status):
                    if usage_meter > 0 and (not offered or offered > 0):
                        connector.status = ChargePointStatus.charging
                    elif usage_meter == 0 and (not offered or offered > 0):
                        connector.status = ChargePointStatus.suspended_ev
                    else:
                        connector.status = ChargePointStatus.suspended_evse

            connector.transaction.usage_meter = usage_meter
            connector.transaction.energy_meter = energy_meter
            connector.transaction.last_usage_time = timestamp

        # Always set the offered field, even if meter_values does not have a transaction_id
        logger.debug(
            f"meter_values: Connector {self.charger_id}/{connector_id} usage_meter {usage_meter},"
            f" energy_meter {energy_meter}, offered {offered} at {time_str(timestamp)}"
        )
        if offered is not None:
            if offered != connector.offered:
                logger.warning(
                    f"Connector {self.charger_id}/{connector_id} reported offer {offered} which is different to "
                    f"expected {connector.offered}. Adjusting it."
                )
                connector.offered = offered
                # Validate that timestamp for the offering is registered. This may not be the case if in
                # a startup case. If so, set to now.
                if connector._bz_last_offer_time is None:
                    connector._bz_last_offer_time = time.time()

        # If in review usage_meter for new max
        connector.update_recent_usage(usage=usage_meter, timestamp=timestamp)


class Group:
    """A group represents a group of chargers.

    Groups with max_allocation set are termed "allocation groups".
    """

    # Static dictionary of Groups. Key is group_id. Value is a Group object.
    group_list: dict[Group] = {}

    def __init__(
        self,
        group_id: str,
        description: str = None,
        max_allocation: str = None,
    ) -> None:
        """constructor

        :raises:
        ModelException: If trying to be bad
        """
        self.group_id = group_id
        self.description = description
        self._max_allocation = max_allocation
        self.chargers: dict[Charger] = {}

        # Internal balanz() fields
        self._bz_suspend: bool = False  # Flag used to suspend balanz() loops, should they be running

        # Insert to the group list
        Group.group_list[group_id] = self
        logger.debug(f"Created group {group_id}")

    def update(self, description: str = None, max_allocation: str = None) -> None:
        """Update specified field on existing group"""
        if description:
            self.description = description
        if max_allocation:
            self._max_allocation = max_allocation

    def external(self, charger_details: bool = False) -> str:
        fields = ["group_id", "description"]
        result = {k: self.__dict__[k] for k in fields}
        if charger_details:
            result["chargers"] = [c.external() for c in self.chargers.values()]
        else:
            result["chargers"] = [c for c in self.chargers]
        result["max_allocation"] = self._max_allocation
        result["max_allocation_now"] = schedule_value_now(self._max_allocation)
        result["offered"] = self.offered()
        result["usage"] = self.usage()
        return result

    def __str__(self) -> str:
        return str(vars(self))

    def max_allocation(self, priority: int = None) -> float:
        """Get max_allocation given the - possibly all day - schedule defined.

        If priority is not supplied, return the value for the largest priority.

        If supplied, the priority value will also be used to determine the max."""
        if self._max_allocation is None:
            return None
        priority_list = schedule_value_now(self._max_allocation)
        return max_priority_allocation(priority_list=priority_list, priority=priority)

    @staticmethod
    def read_csv(file: str) -> None:
        """Read groups from CSV file

        Can be called again. If so will update (if changed) description and max_allocation

        TODO: No support for deleting groups.

        Assumed format: "group_id","description","max_allocation"
        """
        logger.info(f"Reading groups from {file}")
        with open(file, mode="r") as file:
            reader = csv.DictReader(file)
            for group in reader:
                if group["group_id"] in Group.group_list:
                    # Update case
                    g: Group = Group.group_list[group["group_id"]]
                    g.description = group["description"]
                    g._max_allocation = _sn(group["max_allocation"])
                else:
                    # Create case
                    Group(
                        group_id=group["group_id"],
                        description=group["description"],
                        max_allocation=_sn(group["max_allocation"]),
                    )

    @staticmethod
    def write_csv(file: str) -> None:
        """Rewrite groups to CSV file to reflect changes"""
        logger.info(f"Writing groups to {file}")
        with open(file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["group_id", "description", "max_allocation"])
            for g in Group.group_list.values():
                writer.writerow([g.group_id, g.description, _sb(g._max_allocation)])

    @staticmethod
    def allocation_groups() -> list[Group]:
        return [g for g in Group.group_list.values() if g.is_allocation_group()]

    def is_allocation_group(self) -> bool:
        return self._max_allocation is not None

    def all_chargers(self) -> list[Charger]:
        """List of all chargers"""
        return [c for c in self.chargers.values()]

    def chargers_not_init(self) -> list[Charger]:
        """List of chargers that are not initialized yet.

        To be called by balanz loop to ensure all chargers are initialized before calling
        the real balancing logic (balanz()).
        """
        chargers: list[Charger] = self.all_chargers()
        chargers_not_init = [c for c in chargers if not c.profile_initialized and c.ocpp_ref is not None]
        return chargers_not_init

    def chargers_to_request_status(self) -> list[Charger]:
        """List of chargers that need to request status."""
        chargers: list[Charger] = self.all_chargers()
        chargers_to_request = [c for c in chargers if not c.requested_status and c.ocpp_ref is not None]
        return chargers_to_request

    def connectors_reset_blocking(self) -> list[Connector]:
        """List of Connectors for which blocking profile has not been reset AND the connector has ended in a non-transactional state"""
        chargers: list[Charger] = self.all_chargers()
        reset_blocking = [
            conn
            for c in chargers
            for conn in c.connectors.values()
            if conn.transaction is None
            and not status_in_transaction(conn.status)
            and not conn._bz_blocking_profile_reset
        ]
        return reset_blocking

    def transactions_reset_blocking(self) -> list[Transaction]:
        """List of transactions for which the blocking profile has not yet been reset.

        To be called by balanz loop to ensure all the blocking profile is reset once transaction has
            started.
        """
        chargers: list[Charger] = self.all_chargers()
        reset_blocking = [
            conn.transaction
            for c in chargers
            for conn in c.connectors.values()
            if conn.transaction is not None and not conn._bz_blocking_profile_reset
        ]
        return reset_blocking

    def connectors_balanz_review(self) -> list[Connector]:
        """Connectors for (urgent) review, typically after a tag has been scanned.

        To be called by balanz loop to return list of connectors to check urgently.
        The primary case to be covered here is when a connector enters SuspendedEVSE state without
        having a transaction. This indicates an initial connection to be reviewed.
        A special flag will be set balanz to indicate that it has reviewed the situation and the
        connector should no longer be returned in this review list.
        """
        chargers: list[Charger] = self.all_chargers()
        review_list: list[Connector] = [
            conn
            for c in chargers
            for conn in c.connectors.values()
            if conn.status == ChargePointStatus.suspended_evse and conn._bz_to_review
        ]
        return review_list

    def usage(self) -> float:
        """Sum of usage from all chargers in the group"""
        return sum(charger.usage() for charger in self.all_chargers())

    def offered(self) -> float:
        """Sum of offered from all chargers in the group"""
        return sum(charger.offered() for charger in self.all_chargers())

    def balanz(self) -> tuple[list[ChargeChange], list[ChargeChange]]:
        """balanz logic.

        This function should be called regularly on allocation groups to determine what - if any -
        changes to active transaction should be performed. It is then up to the caller to subsequently
        initiate those changes. The caller should either ensure that those changes are either
        performed or discarded before calling balanz again.

        Charging changes to be done will be returned in two lists. First a set of changes
        that will FREE UP capacity, then a list of changes that will USE capacity. It is important
        that the changes are implemented in that order (free up stuff before using it!)

        Once a change has been succesfully implemented, it is the responsibiliy of the caller
        to report this by calling the charge_change_implemented function.

        The algorithm will assume the current allocation to be what has succesfully implemented.
        It is generally assumed that the profiles set will not allow any allocation to non-transactional
        states, so an allocation (offer) of 0 is assumed.

        Chargers will report in the "offered" fields as part of MeterValues calls. These should match
        the ones set via the algorithm. If not, it will be updated and a warning logged.

        2 situations exists which require some special considerations. This relates to starting and suspended
        charging due to "EV full", and suspended charging due to and delayed charging start.

        Starting
        --------
        As, per default, no allocation is assigned to dormant chargers (to allow maximum capacity for others)
        a special trick is required to kick off charging.

        This is because, when a tag is succesfully authorized in the domant/Available state, the charger will
        actually not start a transaction. The only thing that happens is that state goes from Available to
        SuspendedEVSE. This is important as the missing transaction makes it impossible to change the charging
        limit - to start the charging - by setting a transaction specific TxProfile charing profile... Cannot
        set a transaction profile if no transaction exists ...

        The trick to overcome this is as follows. Two default (TxDefaultProfile) charging profiles will be set.
        At the lowest priority is a profile that allows charging at the minimum active level (configurable,
        but typically 6A.) At a higher priority - so shadowing this minimum profile - is another so-called
        shadow profile which does not allow charging (limit is set to 0A).

        Balanz will identify the situation and - if the session is prioritized - return a ChargeChange entry
        to go to the minimum charging (again, configurable, typically 6A) which does not - as it would normally
        do - include a transactionId. The caller is expected to implement this change by temporarily removing
        the shadow default profile. This will allow charging to start, a transaction will be created, and
        further charging changes can then be handled via changes to TxProfile.

        The caller is expected to re-instantiate the shadow default profile. Note, that this will not have any
        effect the the remainder of the transaction, but is important to have in place for the next charging
        session.

        Suspended Charging (EV full case)
        ---------------------------------
        In this situation, charging will have been underway for some time with status as Charging. At some
        point, the charging is complete, and a status notification reports a change from Charging to SuspendedEV.

        A SuspendedEV state means that an allocation/offer is no longer required, and so balanz will return a
        ChargeChange to go to 0. However, what happens next is a bit surprising. Because of this reduction to 0,
        a further status notification puts the status from SuspendedEV to SuspendedEVSE. It is important to
        differentiate this SuspendedEVSE state from other SuspendedEVSE states in which the EV/Charger
        is simply waiting receive an allocation/offer.

        The logic will make use of monitoring reported recent (default 5 minutes) usage_meter values. If the
        maximum usage during this interval is less that a configured minimum (default 2A), then the offer will
        be removed. Also a time stamp will be set (default +1H) for when to again attempt to offer capacity
        to the connector.

        When allocating capacity after a suppension (just like at a regular start), it will always be the
        configured minimum (typically 6A) as it is not given that charging will start - and if not, it would
        be a waste to free up more than the minimum capacity in order to test this.

        Delayed Start
        -------------
        A delayed start scenario start in the same way as a normal start. The difference is that the EV status
        will - after a relatively short time - end up in the SuspendedEV case.

        The logic from this point on will be exactly the same as described in the "Suspended charing" case
        above.

        In general, a reasonable interval between balanz calls would be about 5 minutes.

        Reduction of allocation
        -----------------------
        Balanz will take care not to "over-allocate", i.e. allocate more capacity that the EV wants to
        consume. This comes in two variants.

        IF usage falls below a certain threshold (configurable, default 2A), then allocation is fully removed.

        If usage is above the minimum (i.e. 6A) but below the allocated amount by some amount (configurable,
        default 0.6A), then the allocation will be reduced to the smallest integer higher than current usage.

        In both cases, it is important to make such decisions only when sure that results are stable. To that
        effect, the judgement is make across a (configurable, default 5min) interval.

        The values are retrieved by MeterValues notifications sent by the charger. If the EV/charger reports
        state SuspendedEV, that is naturally taken as a zero-usage measurement. This can be important as some
        charger/EV combinations to not send MeterValues notifications in this state.

        Allocations will be calculated against connectors as some chargers will only start transactions
        (i.e. issue a start_transaction call) when an allocation has been done. In general, allocations
        will be considered - in order of priority - for all connectors in either Charging or SuspendedEVSE
        states.

        :raises:
            ModelException: If called on a non-allocation group.
        """
        if not self.is_allocation_group():
            raise ModelException(f"balanz called on non-allocation group {self.group_id}..")
        logger.debug(f"called balanz on group {self.group_id}")

        ############
        # First, get an overview of the involved chargers, then connectors in relevant states.
        chargers: list[Charger] = self.all_chargers()
        connectors: list[Connector] = [
            conn for c in chargers for conn in c.connectors.values() if status_in_transaction(conn.status)
        ]

        ############
        # Initialize the internal fields we will use on the connectors.
        for conn in connectors:
            if conn.offered is None:
                logger.warning(f"No offered value available for {conn.id_str()}. Assuming 0")
                conn.offered = 0.0  # Assume nothing is offered. This could be dangerous if not correct!
            conn._bz_allocation = 0
            conn._bz_done = False  # Done flag, reset it
            conn._bz_to_review = False  # Will be true shortly, anyway

        ############
        # Check each connector to see if things can be (volentarily) freed up because
        # its not using it's allocation (fully or partially) anymore? Determine how much will be reduced, and
        # prepare the instructions to reduce.
        # For full reduction because the connector is in SuspendedEV state, observe a configurable timeout before
        # making that decision (see comments above.)
        for conn in [c for c in connectors if not c._bz_done]:
            # SuspendedEV case - suspend part
            if conn.status == ChargePointStatus.suspended_ev and conn.get_max_recent_usage() < config.getfloat(
                "balanz", "usage_threshold"
            ):
                if conn._bz_last_offer_time is not None and time.time() - conn._bz_last_offer_time > config.getint(
                    "balanz", "suspended_allocation_timeout"
                ):
                    # Remove allocation and set suspend time.
                    conn._bz_allocation = 0
                    conn._bz_done = True

                    # Is this initial delayed charging?
                    if conn.transaction is not None and conn.transaction.energy_meter >= config.getint(
                        "balanz", "energy_threshold"
                    ):
                        # No!
                        conn._bz_suspend_until = time.time() + config.getint(
                            "balanz", "suspended_delayed_time_not_first"
                        )
                    else:
                        # Yes!
                        if config.getboolean("balanz", "suspend_top_of_hour"):
                            # Adjust to next top of hour and make offer around that time.
                            conn._bz_suspend_until = adjust_time_top_of_hour(
                                time.time(),
                                config.getint("balanz", "suspended_allocation_timeout"),
                            )
                        else:
                            conn._bz_suspend_until = time.time() + config.getint("balanz", "suspended_delayed_time")
                    logger.debug(
                        f"balanz: EV suspended. No allocation for {conn.id_str()}. Suspend until "
                        f"{time_str(conn._bz_suspend_until)}"
                    )
                else:
                    logger.debug(f"allowing continued allocation for suspended EV for now. {conn.id_str()}")
            # SuspendedEVSE / stay suspended case
            elif (
                conn.status == ChargePointStatus.suspended_evse
                and conn._bz_suspend_until is not None
                and time.time() < conn._bz_suspend_until
            ):
                conn._bz_allocation = 0
                conn._bz_done = True
                logger.debug(
                    f"Connector {conn.id_str()} will stay suspended, not yet {time_str(conn._bz_suspend_until)}"
                )
            # Reduce offer case - can an specific limit be determined (EV, end-of-charging ...).
            # Putting quite a few criteria to not be too aggresive on this point.
            elif (
                conn.status == ChargePointStatus.charging
                and conn.transaction is not None
                and conn.transaction.usage_meter is not None
                and time.time() - conn._bz_last_offer_time > config.getint("balanz", "usage_monitoring_interval")
                and conn.get_max_recent_usage() >= config.getfloat("balanz", "min_allocation")
                and conn.offered is not None
                and conn.get_max_recent_usage() <= conn.offered - config.getfloat("balanz", "margin_lower")
                and conn.offered >= config.getfloat("balanz", "min_allocation")
                and not (
                    conn._bz_ev_max_usage is not None and ceil(conn.transaction.usage_meter) > conn._bz_ev_max_usage
                )
            ):
                # Not using full offer (which is above the minimum), so can be reduced.
                # Will be in effect for the rest of the transaction
                conn._bz_allocation = ceil(conn.get_max_recent_usage())
                if conn._bz_allocation < config.getfloat("balanz", "min_allocation"):
                    # Do not to go below the minimum
                    conn._bz_allocation = config.getfloat("balanz", "min_allocation")
                conn._bz_done = True

                # Don't go above this for remainder of session
                if conn._bz_ev_max_usage is None or conn._bz_ev_max_usage > conn._bz_allocation:
                    conn._bz_ev_max_usage = conn._bz_allocation
                    logger.info(
                        f"balanz: Due to EV lower usage, reducing alloc from {conn.offered} to {conn._bz_allocation}"
                        f" for {conn.id_str()}"
                    )

        ############
        # Next, review all connectors asking for allocation and determine their max (desired) usage
        for conn in [c for c in connectors if not c._bz_done]:
            if conn.status == ChargePointStatus.suspended_ev:
                # If - potentially - keeping allocation for a SuspendedEV session, at least do it
                # at the minimum level.
                conn._bz_max = config.getfloat("balanz", "min_allocation")
            else:
                if conn.offered == 0 or conn.transaction is None:
                    logger.debug(f"Setting max offer to min_allocation for {conn.id_str()}.")
                    conn._bz_max = config.getfloat("balanz", "min_allocation")
                else:
                    # Can only increase every X interval
                    if conn._bz_last_offer_time is not None and time.time() - conn._bz_last_offer_time < config.getint(
                        "balanz", "min_offer_increase_interval"
                    ):
                        # Cannot increase yet.
                        conn._bz_max = conn.offered
                        logger.debug(
                            f"Not yet ready to increase offer for {conn.id_str()}. last {time_str(conn._bz_last_offer_time)}"
                        )
                    else:
                        # ... and only if usage has proven to be close to what is offered
                        if conn.offered - conn.get_max_recent_usage() < config.getfloat("balanz", "margin_increase"):
                            conn._bz_max = conn.offered + config.getfloat("balanz", "max_offer_increase")
                            logger.debug(f"Increasing max offer to {conn._bz_max} for {conn.id_str()}.")
                        else:
                            conn._bz_max = conn.offered
                            logger.debug(
                                f"Recent usage for {conn.id_str()} is {conn.get_max_recent_usage()} vs offer {conn.offered}. Too low to increase"
                            )

                    # Is there is an (EV related) max detected?
                    if conn._bz_ev_max_usage is not None:
                        conn._bz_max = min(conn._bz_max, conn._bz_ev_max_usage)
                        logger.debug(f"Restricting {conn.id_str()} to {conn._bz_ev_max_usage} due to history")

                    # But never more than the maximum configured for the connection
                    conn._bz_max = min(conn.conn_max(), conn._bz_max)

        ############
        # Before allocating by priority, the higest priority is to allocate capacity to
        # any connectors that have not yet started a transaction.
        # Note, that max_allocation will default to max priority.
        used_allocation = sum([c._bz_allocation for c in connectors if c._bz_done])
        remain_allocation = self.max_allocation() - used_allocation
        for conn in [
            c
            for c in connectors
            if not c._bz_done
            and conn.transaction is None
            and conn.status == ChargePointStatus.suspended_evse
            and (conn._bz_suspend_until is None or time.time() >= conn._bz_suspend_until)
        ]:
            if remain_allocation >= config.getfloat("balanz", "min_allocation"):
                # It will fit, let's do it
                conn._bz_allocation = config.getfloat("balanz", "min_allocation")
                remain_allocation -= config.getfloat("balanz", "min_allocation")
                logger.debug(f"Allocating minimum allocation to {conn.id_str()}. Remaining now: {remain_allocation}")
                conn._bz_done = True

        ############
        # Next, allocate available capacity by priority up to the calculated max
        # First, get list of priorities in reverse order (highest first)
        priorities = sorted(
            list(set(c.conn_priority() for c in connectors if not c._bz_done)),
            reverse=True,
        )
        # Then list of priority "buckets" now
        priority_buckets = schedule_value_now(self._max_allocation)
        if not priority_buckets:
            logger.error(f"NO priority buckets right now for {self.group_id}. That is critical!")
            raise ModelException(f"No priority bucket for {self.group_id}..")
        max_in_highest_bucket = priority_buckets[0][1]
        for priority in priorities:
            logger.debug(f"{self.group_id} - processing priority {priority}")

            ##########
            # Tricky part. How much is remaining for this priority? First construct
            # table of allocations matching the different entries in the priority_list.
            used_totals = defaultdict(int)
            for used_conn in [c for c in connectors if c._bz_done and c._bz_allocation > 0]:
                # Work out which priority bucket. Note, list is sorted
                for prio_element in priority_buckets:
                    bucket_priority, _ = prio_element
                    if used_conn.conn_priority() >= bucket_priority:
                        used_totals[prio_element] += used_conn._bz_allocation
                        break  # Be sure to only count once!

            # How much remaining in the bucket associated with this priority?
            remaining_in_bucket: float = None
            for prio_element in priority_buckets:
                bucket_priority, ampere = prio_element
                if priority >= bucket_priority:
                    remaining_in_bucket = ampere - used_totals[prio_element]
                    break
            if remaining_in_bucket is None:
                logger.error(f"Remaining_in_bucket is None. priority {priority}. Elements {priority_buckets}")
                remaining_in_bucket = 0

            # Calculate the actual remaining_allocation for this priority
            used_allocation = sum([c._bz_allocation for c in connectors if c._bz_done])
            remain_allocation = min(remaining_in_bucket, max_in_highest_bucket - used_allocation)
            logger.debug(
                f"Remaining in bucket {remaining_in_bucket}, max_in_higest_bucket {max_in_highest_bucket}, "
                f"used_allocation {used_allocation}, remain_allocation {remain_allocation}"
            )

            # Determine the connectors at this priority
            conn_priority = [c for c in connectors if c.conn_priority() == priority and not c._bz_done]

            # Confirm the minimum for as many running connectors as possible. Do not NOT set done flag, unless no room
            for conn in [
                c for c in conn_priority if c.offered > 0 and c._bz_max >= config.getfloat("balanz", "min_allocation")
            ]:
                if remain_allocation >= config.getfloat("balanz", "min_allocation"):
                    # It will fit, let's do it
                    conn._bz_allocation = config.getfloat("balanz", "min_allocation")
                    remain_allocation -= config.getfloat("balanz", "min_allocation")
                else:
                    conn._bz_allocation = 0
                    conn._bz_done = True

            # Next, start further sessions as long as there is room. Do not set done flag, unless no room
            for conn in [
                c for c in conn_priority if c.offered == 0 and c._bz_max >= config.getfloat("balanz", "min_allocation")
            ]:
                if remain_allocation >= config.getfloat("balanz", "min_allocation"):
                    # It will fit, let's do it
                    conn._bz_allocation = config.getfloat("balanz", "min_allocation")
                    remain_allocation -= config.getfloat("balanz", "min_allocation")
                else:
                    conn._bz_allocation = 0
                    conn._bz_done = True

            # Further allocation will be done in a naive round-robin fashion giving 1A per connector until
            # no more available or no more demand (as indicated by _bz_max)
            allocation_in_round = True
            while allocation_in_round:
                # logger.debug(f'  Allocation in round-robin: remain={remain_allocation}')
                allocation_in_round = False
                for conn in conn_priority:
                    if conn._bz_allocation >= conn._bz_max:
                        # At max, done
                        conn._bz_done = True
                    elif remain_allocation > 0:
                        conn._bz_allocation += 1
                        remain_allocation -= 1
                        allocation_in_round = True
                    else:
                        conn._bz_done = True

            # And with that, we are done.
            for conn in conn_priority:
                logger.debug(f"  Offer assigned to {conn.id_str()} is {conn._bz_allocation} A. Done is {conn._bz_done}")

        ############
        # Build result. Each entry will represent a change to be done
        reduce = []
        grow = []
        for conn in [c for c in connectors if c._bz_done]:
            if conn.transaction:
                transaction_id = conn.transaction.transaction_id
            else:
                transaction_id = None

            change = ChargeChange(
                charger_id=conn.charger_id,
                connector_id=conn.connector_id,
                transaction_id=transaction_id,
                allocation=conn._bz_allocation,
            )

            if conn._bz_allocation > conn.offered:
                grow.append(change)
            elif conn._bz_allocation < conn.offered:
                reduce.append(change)
            # Note the == case is silently dropped
        return reduce, grow


class Tag:
    """A Tag represents an RFID tag/card. It is associated with a user."""

    # Static dictionary of Tags. Key is id_tag.
    tag_list: dict[Tag] = {}

    def __init__(
        self,
        id_tag: str,
        user_name: str,
        parent_id_tag: str = None,
        description: str = None,
        status: TagStatusType = TagStatusType.activated,
        priority: int = None,
    ) -> None:
        self.id_tag = id_tag.upper()
        self.user_name = user_name
        self.parent_id_tag = parent_id_tag
        self.description = description
        self.status = TagStatusType.activated if status == "Activated" else TagStatusType.blocked
        self.priority = priority
        Tag.tag_list[self.id_tag] = self
        logger.debug(f"Created tag {self.id_tag} for user {user_name}. Status is {status}")

    def update(
        self,
        user_name: str = None,
        parent_id_tag: str = None,
        description: str = None,
        status: str = None,
        priority: int = None,
    ) -> None:
        """Update specified values on an existing tag"""
        if user_name:
            self.user_name = user_name
        if parent_id_tag:
            self.parent_id_tag = parent_id_tag
        if description:
            self.description = description
        if status:
            self.status = TagStatusType.activated if status == "Activated" else TagStatusType.blocked
        if priority:
            self.priority = priority

    def external(self) -> str:
        fields = ["id_tag", "user_name", "parent_id_tag", "description", "status", "priority"]
        result = {k: self.__dict__[k] for k in fields}
        return result

    @staticmethod
    def read_csv(file: str) -> None:
        """
        Read tags from CSV file

        May be called again to reload tags file.

        Assumed format: "id_tag","user_name","parent_id_tag","description","status","priority"
        """
        logger.info(f"Reading tags from {file}")
        # Delete any existing elements.
        Tag.tag_list.clear()
        with open(file, mode="r") as file:
            reader = csv.DictReader(file)
            for tag in reader:
                priority = _in(tag["priority"]) if "priority" in tag else None
                Tag(
                    id_tag=tag["id_tag"],
                    user_name=_sn(tag["user_name"]),
                    parent_id_tag=_sn(tag["parent_id_tag"]),
                    description=tag["description"],
                    status=_sn(tag["status"]),
                    priority=priority,
                )
        logger.info(f"Read {len(Tag.tag_list)} tags")

    @staticmethod
    def write_csv(file: str) -> None:
        """Rewrite tags to CSV file to reflect changes"""
        logger.info(f"Writing tags to {file}")
        with open(file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "id_tag",
                    "user_name",
                    "parent_id_tag",
                    "description",
                    "status",
                    "priority",
                ]
            )
            for tag in Tag.tag_list.values():
                writer.writerow(
                    [
                        tag.id_tag,
                        _sb(tag.user_name),
                        _sb(tag.parent_id_tag),
                        _sb(tag.description),
                        tag.status,
                        _sb(tag.priority),
                    ]
                )

    def __str__(self) -> str:
        return str(vars(self))
