"""The SDK's standard-library logs reach loguru (ADR-0089)."""

import logging

from loguru import logger

import styrmin_backend  # noqa: F401  # importing the package installs the forwarding
from styrmin_backend.logging_bridge import SDK_LOGGER_NAME, install_sdk_log_forwarding


def test_a_warning_of_the_driver_format_code_reaches_a_loguru_sink() -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{level} {message}")
    try:
        logging.getLogger(
            "styrmin_sdk.driver_format.context.models.components"
        ).warning("Ignoring the invalid keys %s of component %s%s", ["x"], "server", "")
    finally:
        logger.remove(sink)

    assert messages == ["WARNING Ignoring the invalid keys ['x'] of component server\n"]


def test_installing_twice_adds_one_handler() -> None:
    install_sdk_log_forwarding()
    install_sdk_log_forwarding()

    assert len(logging.getLogger(SDK_LOGGER_NAME).handlers) == 1
    assert logging.getLogger(SDK_LOGGER_NAME).propagate is False
