"""Shared test fixtures for styrminctl CLI tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def mock_client(mocker: MockerFixture) -> MagicMock:
    """Create a mock StyrminClient and patch get_client to return it."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("styrminctl.client.get_client", return_value=client)
    return client
