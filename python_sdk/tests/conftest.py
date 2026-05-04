"""Shared test fixtures for SDK tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import Transport
from styrmin_sdk.client import StyrminClient
from styrmin_sdk.resources.auth import AuthResource
from styrmin_sdk.resources.backups import BackupResource
from styrmin_sdk.resources.clusters import ClusterResource
from styrmin_sdk.resources.deployments import DeploymentResource
from styrmin_sdk.resources.drivers import DriverResource
from styrmin_sdk.resources.environments import EnvironmentResource
from styrmin_sdk.resources.schedules import ScheduleResource
from styrmin_sdk.resources.tasks import TaskResource


@pytest.fixture
def mock_transport() -> AsyncMock:
    """Return a mocked Transport whose ``execute`` method can be configured per-test."""
    transport = AsyncMock(spec=Transport)
    transport.close = AsyncMock()
    return transport


@pytest.fixture
def client(mock_transport: AsyncMock) -> StyrminClient:
    """Return an StyrminClient wired to *mock_transport*."""
    c = StyrminClient.__new__(StyrminClient)
    c._transport = mock_transport

    c.auth = AuthResource(mock_transport)
    c.clusters = ClusterResource(mock_transport)
    c.environments = EnvironmentResource(mock_transport)
    c.drivers = DriverResource(mock_transport)
    c.deployments = DeploymentResource(mock_transport)
    c.tasks = TaskResource(mock_transport)
    c.backups = BackupResource(mock_transport)
    c.schedules = ScheduleResource(mock_transport)
    return c


def make_graphql_response(data: dict[str, Any]) -> dict[str, Any]:
    """Helper to wrap data in a GraphQL-style response."""
    return data
