import logging

import pytest

from styrmin_backend.agent.service.kubernetes.dependency import (
    _build_kubeconfig_dict,
    get_api_client,
)
from styrmin_backend.config import KubernetesConfigMode


class TestBuildKubeconfigDict:
    def test_with_ca_cert(self):
        result = _build_kubeconfig_dict(
            host="https://k8s.example.com",
            token="my-token",
            ca_cert="base64-cert-data",
        )
        cluster_config = result["clusters"][0]["cluster"]
        assert cluster_config["server"] == "https://k8s.example.com"
        assert cluster_config["certificate-authority-data"] == "base64-cert-data"
        assert "insecure-skip-tls-verify" not in cluster_config

    def test_without_ca_cert(self):
        result = _build_kubeconfig_dict(
            host="https://k8s.example.com",
            token="my-token",
        )
        cluster_config = result["clusters"][0]["cluster"]
        assert cluster_config["server"] == "https://k8s.example.com"
        assert cluster_config["insecure-skip-tls-verify"] is True
        assert "certificate-authority-data" not in cluster_config

    def test_token_in_user(self):
        result = _build_kubeconfig_dict(
            host="https://k8s.example.com",
            token="my-token",
        )
        user_config = result["users"][0]["user"]
        assert user_config["token"] == "my-token"

    def test_structure(self):
        result = _build_kubeconfig_dict(
            host="https://k8s.example.com",
            token="my-token",
        )
        assert result["apiVersion"] == "v1"
        assert result["kind"] == "Config"
        assert result["current-context"] == "envvars"
        assert len(result["clusters"]) == 1
        assert len(result["contexts"]) == 1
        assert len(result["users"]) == 1
        assert result["contexts"][0]["context"]["cluster"] == "envvars"
        assert result["contexts"][0]["context"]["user"] == "envvars"


class TestGetApiClient:
    async def test_incluster_mode(self, mocker, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "incluster")

        mock_settings = mocker.MagicMock()
        mock_settings.config_mode = KubernetesConfigMode.INCLUSTER
        mocker.patch("styrmin_backend.config.SETTINGS").kubernetes = mock_settings

        mock_load = mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.kubeconfig.load_incluster_config"
        )
        mock_api = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.ApiClient",
            return_value=mock_api,
        )
        mock_api.__aenter__ = mocker.AsyncMock(return_value=mock_api)
        mock_api.__aexit__ = mocker.AsyncMock(return_value=False)

        gen = get_api_client()
        client = await gen.__anext__()

        mock_load.assert_called_once()
        assert client is mock_api

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    async def test_kubeconfig_mode(self, mocker, monkeypatch):
        monkeypatch.setenv("KUBECONFIG", "/home/user/.kube/config")

        mock_settings = mocker.MagicMock()
        mock_settings.config_mode = KubernetesConfigMode.KUBECONFIG
        mocker.patch("styrmin_backend.config.SETTINGS").kubernetes = mock_settings

        mock_load = mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.kubeconfig.load_kube_config",
            new_callable=mocker.AsyncMock,
        )
        mock_api = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.ApiClient",
            return_value=mock_api,
        )
        mock_api.__aenter__ = mocker.AsyncMock(return_value=mock_api)
        mock_api.__aexit__ = mocker.AsyncMock(return_value=False)

        gen = get_api_client()
        client = await gen.__anext__()

        mock_load.assert_called_once_with(config_file="/home/user/.kube/config")
        assert client is mock_api

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    async def test_kubeconfig_mode_without_env_var(self, mocker, monkeypatch):
        monkeypatch.delenv("KUBECONFIG", raising=False)

        mock_settings = mocker.MagicMock()
        mock_settings.config_mode = KubernetesConfigMode.KUBECONFIG
        mocker.patch("styrmin_backend.config.SETTINGS").kubernetes = mock_settings

        mock_load = mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.kubeconfig.load_kube_config",
            new_callable=mocker.AsyncMock,
        )
        mock_api = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.ApiClient",
            return_value=mock_api,
        )
        mock_api.__aenter__ = mocker.AsyncMock(return_value=mock_api)
        mock_api.__aexit__ = mocker.AsyncMock(return_value=False)

        gen = get_api_client()
        await gen.__anext__()

        mock_load.assert_called_once_with(config_file=None)

    async def test_envvars_mode(self, mocker):
        mock_settings = mocker.MagicMock()
        mock_settings.config_mode = KubernetesConfigMode.ENVVARS
        mock_settings.host = "https://k8s.example.com"
        mock_settings.token = "my-token"
        mock_settings.ca_cert = None
        mocker.patch("styrmin_backend.config.SETTINGS").kubernetes = mock_settings

        mock_load = mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.kubeconfig.load_kube_config_from_dict",
            new_callable=mocker.AsyncMock,
        )
        mock_api = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.ApiClient",
            return_value=mock_api,
        )
        mock_api.__aenter__ = mocker.AsyncMock(return_value=mock_api)
        mock_api.__aexit__ = mocker.AsyncMock(return_value=False)

        gen = get_api_client()
        client = await gen.__anext__()

        mock_load.assert_called_once()
        config_dict = mock_load.call_args.kwargs["config_dict"]
        assert (
            config_dict["clusters"][0]["cluster"]["server"] == "https://k8s.example.com"
        )
        assert config_dict["users"][0]["user"]["token"] == "my-token"
        assert client is mock_api

    async def test_logs_config_mode_at_info_level(self, mocker, caplog):
        mock_settings = mocker.MagicMock()
        mock_settings.config_mode = KubernetesConfigMode.INCLUSTER
        mocker.patch("styrmin_backend.config.SETTINGS").kubernetes = mock_settings

        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.kubeconfig.load_incluster_config"
        )
        mock_api = mocker.AsyncMock()
        mocker.patch(
            "styrmin_backend.agent.service.kubernetes.dependency.ApiClient",
            return_value=mock_api,
        )
        mock_api.__aenter__ = mocker.AsyncMock(return_value=mock_api)
        mock_api.__aexit__ = mocker.AsyncMock(return_value=False)

        with caplog.at_level(
            logging.INFO, logger="styrmin_backend.agent.service.kubernetes.dependency"
        ):
            gen = get_api_client()
            await gen.__anext__()

        assert any("incluster" in record.message for record in caplog.records)
