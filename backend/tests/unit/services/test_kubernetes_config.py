import pytest
from pydantic import ValidationError

from styrmin_backend.config import KubernetesConfigMode, KubernetesSettings


class TestKubernetesConfigMode:
    def test_incluster_mode(self):
        assert KubernetesConfigMode.INCLUSTER == "incluster"

    def test_kubeconfig_mode(self):
        assert KubernetesConfigMode.KUBECONFIG == "kubeconfig"

    def test_envvars_mode(self):
        assert KubernetesConfigMode.ENVVARS == "envvars"


class TestKubernetesSettings:
    def test_default_mode_is_incluster(self):
        settings = KubernetesSettings()
        assert settings.config_mode == KubernetesConfigMode.INCLUSTER

    def test_envvars_mode_with_host_and_token(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        monkeypatch.setenv("STYRMIN_K8S_HOST", "https://k8s.example.com")
        monkeypatch.setenv("STYRMIN_K8S_TOKEN", "my-token")
        settings = KubernetesSettings()
        assert settings.config_mode == KubernetesConfigMode.ENVVARS
        assert settings.host == "https://k8s.example.com"
        assert settings.token == "my-token"

    def test_envvars_mode_without_host_raises(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        monkeypatch.setenv("STYRMIN_K8S_TOKEN", "my-token")
        with pytest.raises(ValidationError, match="KUBERNETES_HOST"):
            KubernetesSettings()

    def test_envvars_mode_without_token_raises(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        monkeypatch.setenv("STYRMIN_K8S_HOST", "https://k8s.example.com")
        with pytest.raises(ValidationError, match="KUBERNETES_TOKEN"):
            KubernetesSettings()

    def test_envvars_mode_without_host_and_token_raises(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        with pytest.raises(ValidationError, match="KUBERNETES_HOST"):
            KubernetesSettings()

    def test_alias_env_var_kubernetes_config_mode(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_CONFIG_MODE", "kubeconfig")
        settings = KubernetesSettings()
        assert settings.config_mode == KubernetesConfigMode.KUBECONFIG

    def test_alias_env_var_kubernetes_host(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        monkeypatch.setenv("KUBERNETES_HOST", "https://k8s.example.com")
        monkeypatch.setenv("KUBERNETES_TOKEN", "my-token")
        settings = KubernetesSettings()
        assert settings.host == "https://k8s.example.com"
        assert settings.token == "my-token"

    def test_ca_cert_optional(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "envvars")
        monkeypatch.setenv("STYRMIN_K8S_HOST", "https://k8s.example.com")
        monkeypatch.setenv("STYRMIN_K8S_TOKEN", "my-token")
        monkeypatch.setenv("STYRMIN_K8S_CA_CERT", "base64-cert-data")
        settings = KubernetesSettings()
        assert settings.ca_cert == "base64-cert-data"

    def test_ca_cert_defaults_to_none(self):
        settings = KubernetesSettings()
        assert settings.ca_cert is None

    def test_incluster_mode_does_not_require_host_or_token(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "incluster")
        settings = KubernetesSettings()
        assert settings.config_mode == KubernetesConfigMode.INCLUSTER
        assert settings.host is None
        assert settings.token is None

    def test_kubeconfig_mode_does_not_require_host_or_token(self, monkeypatch):
        monkeypatch.setenv("STYRMIN_K8S_CONFIG_MODE", "kubeconfig")
        settings = KubernetesSettings()
        assert settings.config_mode == KubernetesConfigMode.KUBECONFIG
        assert settings.host is None
        assert settings.token is None
