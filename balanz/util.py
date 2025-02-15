"""
Various utility functions used by multiple modules.
"""

import hashlib
import math
import re

__all__ = [
    "time_str",
    "duration_str",
    "kwh_str",
    "status_in_transaction",
    "parse_time",
    "schedule_value_now",
]

from datetime import datetime, time

from ocpp.v16.enums import ChargePointStatus


def time_str(t: float) -> str:
    """Converts a timestamp to a string (local time)"""
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else "N/A"


def parse_time(timestamp: str) -> float:
    """Parses an ISO timestamp (i.e. a timestamp with a time zone indicator, either +xx:xx or Z for Zulu)"""
    if len(timestamp) == 0:
        return None
    return datetime.fromisoformat(timestamp).timestamp()


def adjust_time_top_of_hour(timestamp: float, interval: float) -> float:
    """Adjusts a timestamp to the top of the hour returning a timestamp
    which is interval/2 seconds before the (next) top of the hour"""
    next_hour = math.ceil(timestamp / 3600) * 3600
    return next_hour - interval / 2


def duration_str(dur: float) -> str:
    """Presents a duration nicely ([H]*HH:MM:SS). Note, could have 3-4 digits of H ..."""
    hours, remainder = divmod(int(dur), 3600)
    minutes, seconds = divmod(remainder, 60)
    return str(hours).zfill(2) + ":" + str(minutes).zfill(2) + ":" + str(seconds).zfill(2)


def kwh_str(energy: int) -> str:
    """Formats energy usage in Wh as kWh with suitable decimals"""
    return f"{energy / 1000.0:.3f}"


def status_in_transaction(status) -> bool:
    """Check if charger status is associated with a transaction"""
    return status in [
        ChargePointStatus.charging,
        ChargePointStatus.suspended_evse,
        ChargePointStatus.suspended_ev,
    ]


def schedule_value_now(schedule: str) -> list[tuple[int, float]]:
    """Get value (list of priority/Ampere pairs) defined in schedule that is valid now

    Example: '00:00-05:59>0=48;06:00-16:59>0=16:3=32:5=48;17:00-20:59>0=0:5=48;21:00-23:59>0=32:5=48'
    Returns list of tuples (priority, Ampere) value for first matched interval (they should not
    overlap, but could). Returns None if no interval covers current time (should not happen!)
    """
    if schedule is None:
        return []

    dt = datetime.now()
    now_hour = dt.hour
    now_mm = dt.minute
    now = time(hour=now_hour, minute=now_mm)

    intervals = re.findall(r"((\d\d):(\d\d)-(\d\d):(\d\d)>([^;]+))", schedule)
    for int_string, start_hh, start_mm, end_hh, end_mm, value in intervals:
        start = time(hour=int(start_hh), minute=int(start_mm))
        end = time(hour=int(end_hh), minute=int(end_mm), second=59, microsecond=1000000 - 1)
        if now >= start and now <= end:
            prio_settings = re.findall(r"((\d+)=(\d+))", value)
            prio_list = [(int(prio), float(amp)) for _, prio, amp in prio_settings]
            prio_list.sort(reverse=True)
            return prio_list
    return None


def schedule_value_now_external(schedule: str) -> str:
    """Pretty print version of schedule_value_now.

    Will return black if schedule is None (the case for non-allocation groups)"""
    if schedule is None:
        return ""
    return ":".join([f"p{priority}={ampere}A" for (priority, ampere) in schedule_value_now(schedule)])


def max_priority_allocation(priority_list: list[tuple[int, float]], priority: int = None) -> float:
    """Uses schedule returned from schedule_value_now and returns allow max_allocation

    If priority is not given, return the Amp value for the highest priority (the first element)
    """
    if priority is None and priority_list:
        _, amp = priority_list[0]
        return amp

    for prio, amp in priority_list:
        if priority >= prio:
            return amp
    return 0


def gen_sha_256(request_auth: str) -> str:
    """Generate sha256

    Note: Will be lowercase
    """
    return hashlib.sha256(request_auth.encode("utf-8")).hexdigest()
