import logging
import os
from typing import Any, AsyncGenerator

from kubernetes_asyncio import config as kubeconfig
from kubernetes_asyncio.client.api_client import ApiClient

from styrmin_backend import config

logger = logging.getLogger(__name__)


def _build_kubeconfig_dict(
    host: str, token: str, ca_cert: str | None = None
) -> dict[str, Any]:
    """Build a kubeconfig dict from environment variable values.

    This dict matches the standard kubeconfig YAML structure expected
    by kubernetes-asyncio's load_kube_config_from_dict().
    """
    cluster_config: dict[str, Any] = {"server": host}
    if ca_cert:
        cluster_config["certificate-authority-data"] = ca_cert
    else:
        cluster_config["insecure-skip-tls-verify"] = True

    return {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": "envvars",
        "clusters": [
            {
                "name": "envvars",
                "cluster": cluster_config,
            }
        ],
        "contexts": [
            {
                "name": "envvars",
                "context": {"cluster": "envvars", "user": "envvars"},
            }
        ],
        "users": [
            {
                "name": "envvars",
                "user": {"token": token},
            }
        ],
    }


async def load_kubernetes_config() -> None:
    """Load Kubernetes configuration based on the configured mode."""
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    settings = config.SETTINGS.kubernetes
    mode = settings.config_mode

    logger.debug("Kubernetes config mode: %s", mode.value)

    if mode == config.KubernetesConfigMode.INCLUSTER:
        try:
            kubeconfig.load_incluster_config()
        except kubeconfig.ConfigException as exc:
            msg = f"Failed to load in-cluster Kubernetes config. Are you running inside a Kubernetes pod? Error: {exc}"
            raise kubeconfig.ConfigException(msg) from exc

    elif mode == config.KubernetesConfigMode.KUBECONFIG:
        config_file = os.environ.get("KUBECONFIG", None)
        try:
            await kubeconfig.load_kube_config(config_file=config_file)
        except Exception as exc:
            path = config_file or "~/.kube/config"
            msg = f"Failed to load kubeconfig from '{path}'. Verify the file exists and is valid. Error: {exc}"
            raise kubeconfig.ConfigException(msg) from exc

    elif mode == config.KubernetesConfigMode.ENVVARS:
        config_dict = _build_kubeconfig_dict(
            host=settings.host,  # type: ignore[arg-type]
            token=settings.token,  # type: ignore[arg-type]
            ca_cert=settings.ca_cert,
        )
        await kubeconfig.load_kube_config_from_dict(config_dict=config_dict)

    else:
        valid_modes = ", ".join(m.value for m in config.KubernetesConfigMode)
        msg = f"Invalid KUBERNETES_CONFIG_MODE: '{mode}'. Valid modes: {valid_modes}"
        raise ValueError(msg)


async def get_api_client() -> AsyncGenerator[ApiClient, None]:
    await load_kubernetes_config()

    async with ApiClient() as api:
        yield api
