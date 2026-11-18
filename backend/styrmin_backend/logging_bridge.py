"""Forward the standard-library logs of the SDK to loguru.

The driver format code moved to ``styrmin_sdk.driver_format`` (ADR-0089) and logs with the
standard library, as a library does. The server, the agent and the tests read loguru's
output, so this handler forwards every record of the ``styrmin_sdk`` logger to loguru,
with its level and message. ``styrmin_backend/__init__.py`` installs it once per process.
"""

import logging

from loguru import logger

SDK_LOGGER_NAME = "styrmin_sdk"


class _LoguruHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def install_sdk_log_forwarding() -> None:
    """Forward the ``styrmin_sdk`` logger to loguru. Calling it again changes nothing."""
    sdk_logger = logging.getLogger(SDK_LOGGER_NAME)
    if any(isinstance(h, _LoguruHandler) for h in sdk_logger.handlers):
        return
    sdk_logger.addHandler(_LoguruHandler())
    sdk_logger.setLevel(logging.DEBUG)
    # The records reach loguru once; without this, a root handler would print them again.
    sdk_logger.propagate = False
