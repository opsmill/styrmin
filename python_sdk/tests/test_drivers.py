"""Tests for driver resource operations."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import OperationFailedError, StyrminClient


async def test_list_drivers(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "applicationDrivers": [
                {
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "name": "infrahub",
                    "versions": [
                        {
                            "id": "11111111-2222-3333-4444-555555555555",
                            "version": "1.0.0",
                            "supportedVersions": ">=1.0",
                        },
                        {
                            "id": "66666666-7777-8888-9999-000000000000",
                            "version": "1.1.0",
                            "supportedVersions": ">=1.1",
                        },
                    ],
                },
                {"id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff", "name": "nautobot", "versions": []},
            ]
        }
    }

    drivers = await client.drivers.list()

    assert [driver.name for driver in drivers] == ["infrahub", "nautobot"]
    assert [version.version for version in drivers[0].versions] == ["1.0.0", "1.1.0"]
    assert drivers[0].versions[1].supported_versions == ">=1.1"
    assert drivers[1].versions == []


async def test_list_drivers_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"applicationDrivers": []}}

    assert await client.drivers.list() == []


async def test_list_drivers_graphql_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"errors": [{"message": "boom"}]}

    with pytest.raises(OperationFailedError):
        await client.drivers.list()
