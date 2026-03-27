"""Shared client construction for styrminctl commands."""

from __future__ import annotations

from styrmin_sdk import StyrminClient

from styrminctl.config import SETTINGS


def get_client() -> StyrminClient:
    """Create a configured StyrminClient instance."""
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )
