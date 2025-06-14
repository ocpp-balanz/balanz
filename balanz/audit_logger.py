import logging

from config import config
from memory_log_handler import MemoryLogHandler

# #################################################
# Set-up logging stuff

# audit file handler

audit_logger = logging.getLogger("AUDIT")

# TODO: Read audit file to memory_log_handler upon startup...
