import logging
import re
from collections import deque
from datetime import datetime
from typing import Optional


class MemoryLogHandler(logging.Handler):
    api_instance: Optional["MemoryLogHandler"] = None

    def __init__(self, capacity=100000):
        super().__init__()
        self.capacity = capacity
        self.logs = deque(maxlen=capacity)  # bounded log memory

    def set_api_instance(self):
        if not MemoryLogHandler.api_instance:
            MemoryLogHandler.api_instance = self

    def emit(self, record):
        if record.levelno >= logging.INFO:  # Only store INFO and above
            if self.formatter:
                # Ensure exact timestamp format as console
                timestamp = self.formatter.formatTime(record, self.formatter.datefmt)
            else:
                timestamp = record.created  # fallback: raw float

            log_entry = {
                "level": record.levelname,
                "message": record.getMessage(),
                "timestamp": timestamp,
                "logger": record.name,
            }
            self.logs.append(log_entry)

    def get_logs(self):
        return list(self.instance.logs)  # shallow copy

    def get_api_logs(filters=None):
        if filters is None:
            return list(MemoryLogHandler.api_instance.logs)  # shallow copy
        else:
            filtered_logs = []
            for log in MemoryLogHandler.api_instance.logs:
                # Filter is a record with optional fields level, messageSearch, timestampStart and timestampEnd, module
                # Check log level. Continue if log level lower than filter
                if "level" in filters and log["level"] < filters.get("level"):
                    continue
                # Check message. Continue if no filter for message, or if the message does not match the search pattern.
                if "messageSearch" in filters:
                    if log["message"].find(filters.get("messageSearch")) == -1:
                        continue
                # Check timestamp. Continue if no filter for start time, or if the log's timestamp is before the start time.
                if "timeStampStart" in filters:
                    if log["timestamp"] < filters.get("timeStampStart"):
                        continue
                # End timestamp
                if "timeStampEnd" in filters:
                    if log["timestamp"] > filters.get("timeStampEnd"):
                        continue
                # Module (note, that this includes AUDIT)
                if "logger" in filters:
                    if log["logger"] != filters.get("logger"):
                        continue
                # Add to filtered logs list.
                filtered_logs.append(log)
            return filtered_logs

    def parse_log_file(self, filepath):
        LOG_LINE_REGEX = re.compile(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
            r"(?P<level>\w+) "
            r"(?P<logger>[\w_.-]+): "
            r"(?P<message>.*)$"
        )
        parsed_logs = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                match = LOG_LINE_REGEX.match(line)
                if not match:
                    print(f"Warning: Line {line_number} didn't match expected format.")
                    continue

                groups = match.groupdict()
                parsed_log = {
                    "timestamp": groups["timestamp"],  # kept as string
                    "level": groups["level"],
                    "logger": groups["logger"],
                    "message": groups["message"],
                }

                self.logs.append(parsed_log)
