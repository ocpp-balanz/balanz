import logging
from collections import deque
from typing import Optional

class MemoryLogHandler(logging.Handler):

    def __init__(self, capacity=1000):
        super().__init__()
        self.capacity = capacity
        self.logs = deque(maxlen=capacity)  # bounded log memory

    def emit(self, record):
        if record.levelno >= logging.INFO:  # Only store INFO and above
            if self.formatter:
                # Ensure exact timestamp format as console
                timestamp = self.formatter.formatTime(record, self.formatter.datefmt)
            else:
                timestamp = record.created  # fallback: raw float

            log_entry = {
                'level': record.levelname,
                'message': record.getMessage(),
                'timestamp': timestamp,
                'module': record.module,
            }
            self.logs.append(log_entry)

    def get_logs(self):
        return list(self.instance.logs)  # shallow copy
