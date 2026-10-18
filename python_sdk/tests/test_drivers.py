"""Tests for driver resource operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import IncompatibleServerError, OperationFailedError, StyrminClient


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
                            "sourceType": "git",
                            "sourceRepository": "https://git.example.com/drivers.git",
                            "sourceBranch": "main",
                            "sourcePath": "drivers/infrahub",
                            "contentHash": None,
                            "sourceCommitSha": "def4567890abcdef1234567890abcdef12345678",
                        },
                        {
                            "id": "66666666-7777-8888-9999-000000000000",
                            "version": "1.1.0",
                            "supportedVersions": ">=1.1",
                            "sourceType": "local",
                            "sourceRepository": "",
                            "sourceBranch": None,
                            "sourcePath": "/srv/drivers/infrahub",
                            "contentHash": "abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
                            "sourceCommitSha": None,
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
    assert drivers[0].versions[0].source_type == "git"
    assert drivers[0].versions[0].source_path == "drivers/infrahub"
    assert drivers[0].versions[1].source_path == "/srv/drivers/infrahub"
    assert drivers[1].versions == []


async def test_list_drivers_empty(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"applicationDrivers": []}}

    assert await client.drivers.list() == []


async def test_list_drivers_graphql_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"errors": [{"message": "boom"}]}

    with pytest.raises(OperationFailedError):
        await client.drivers.list()


def _load_remote_response(source_path: str | None) -> dict[str, Any]:
    response: dict[str, Any] = {
        "data": {
            "loadRemoteApplicationDriverVersion": {
                "id": "11111111-2222-3333-4444-555555555555",
                "applicationDriverId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "applicationDriver": {"name": "infrahub"},
                "version": "1.0.0",
                "contentHash": None,
                "sourceCommitSha": "def4567890abcdef1234567890abcdef12345678",
                "sourceRepository": "https://git.example.com/drivers.git",
                "sourceBranch": "main",
                "sourcePath": source_path,
                "loadWarnings": [],
                "supportedVersions": ">=1.0",
                "components": None,
                "componentConfigs": [],
                "actions": [],
                "helmChart": {
                    "id": "66666666-7777-8888-9999-000000000000",
                    "name": "infrahub",
                    "version": "1.0.0",
                    "repository": "oci://registry.example.com/charts",
                    "valueTemplate": "",
                },
            }
        }
    }
    if source_path is not None:
        response["data"]["loadRemoteApplicationDriverVersion"]["driverDirectory"] = source_path
    return response


async def test_load_version_sends_driver_directory(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = _load_remote_response("drivers/a")

    version = await client.drivers.load_version(
        "https://git.example.com/drivers.git", "main", driver_directory="drivers/a"
    )

    query, variables = mock_transport.execute.call_args.args
    assert "mutation LoadVersionWithDriverDirectory(" in query
    assert variables == {
        "repositoryUrl": "https://git.example.com/drivers.git",
        "branch": "main",
        "driverDirectory": "drivers/a",
    }
    assert version.source_path == "drivers/a"
    assert getattr(version, "driver_directory", None) == "drivers/a"
    assert version.source_repository == "https://git.example.com/drivers.git"
    assert version.source_branch == "main"


async def test_load_version_without_driver_directory_omits_the_variable(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = _load_remote_response(None)

    version = await client.drivers.load_version("https://git.example.com/drivers.git", "main")

    query, variables = mock_transport.execute.call_args.args
    # The operation without ``driverDirectory`` works against servers older than #517.
    assert "mutation LoadRemoteApplicationDriverVersion(" in query
    assert "driverDirectory" not in query
    assert "driverDirectory" not in variables
    assert variables == {"repositoryUrl": "https://git.example.com/drivers.git", "branch": "main"}
    assert version.source_path is None


async def test_load_version_with_driver_directory_on_an_older_server_raises(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = {
        "data": None,
        "errors": [
            {
                "message": "Unknown argument 'driverDirectory' on field 'Mutation.loadRemoteApplicationDriverVersion'.",
            }
        ],
    }

    with pytest.raises(IncompatibleServerError, match="Upgrade the Styrmin server"):
        await client.drivers.load_version("https://git.example.com/drivers.git", "main", driver_directory="drivers/a")
