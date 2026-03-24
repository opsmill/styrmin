from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client.api_client import ApiClient

from styrmin_backend.workflows.connectivity import validate_kubernetes_connectivity
from styrmin_backend.workflows.models import KubernetesConnectivityResult


@pytest.fixture
def mock_k8s_client(mocker):
    """Mock get_api_client at the connectivity module level."""
    mock_config = mocker.MagicMock()
    mock_client = mocker.MagicMock(spec=ApiClient, configuration=mock_config)

    async def _fake_get_api_client():
        yield mock_client

    mocker.patch(
        "styrmin_backend.workflows.connectivity.get_api_client",
        return_value=_fake_get_api_client(),
    )
    return mock_client


class TestValidateKubernetesConnectivity:
    async def test_success_returns_connected(self, mocker, mock_k8s_client):
        mock_k8s_client.configuration.host = "https://k8s.example.com"

        mock_v1 = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.workflows.connectivity.CoreV1Api",
            return_value=mock_v1,
        )

        result = await validate_kubernetes_connectivity.fn()

        assert isinstance(result, KubernetesConnectivityResult)
        assert result.connected is True
        assert result.cluster_info == "https://k8s.example.com"
        assert result.error is None
        mock_v1.list_namespace.assert_awaited_once_with(limit=1)

    async def test_failure_returns_not_connected(self, mocker, mock_k8s_client):
        mock_v1 = mocker.AsyncMock()
        mock_v1.list_namespace = AsyncMock(side_effect=Exception("Connection refused"))
        mocker.patch(
            "styrmin_backend.workflows.connectivity.CoreV1Api",
            return_value=mock_v1,
        )

        result = await validate_kubernetes_connectivity.fn()

        assert isinstance(result, KubernetesConnectivityResult)
        assert result.connected is False
        assert result.cluster_info is None
        assert result.error is not None
        assert "Connection refused" in result.error
