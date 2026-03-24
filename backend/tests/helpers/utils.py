import time

import requests
from testcontainers.core.container import DockerContainer
from pathlib import Path
from kubernetes_asyncio.client import (
    V1Deployment,
    V1Service,
    V1ServiceAccount,
    V1ClusterRoleBinding,
)
import yaml


def get_kubernetes_deployment_from_path(path: Path) -> V1Deployment:
    with open(path) as deployment_file:
        deployment_data = yaml.safe_load(deployment_file)

    return V1Deployment(
        api_version=deployment_data["apiVersion"],
        kind=deployment_data["kind"],
        metadata=deployment_data["metadata"],
        spec=deployment_data["spec"],
    )


def get_kubernetes_service_from_path(path: Path) -> V1Service:
    with open(path) as service_file:
        service_data = yaml.safe_load(service_file)

    return V1Service(
        api_version=service_data["apiVersion"],
        kind=service_data["kind"],
        metadata=service_data["metadata"],
        spec=service_data["spec"],
    )


def get_kubernetes_service_account_from_path(path: Path) -> V1ServiceAccount:
    with open(path) as sa_file:
        sa_data = yaml.safe_load(sa_file)

    return V1ServiceAccount(
        api_version=sa_data["apiVersion"],
        kind=sa_data["kind"],
        metadata=sa_data["metadata"],
        automount_service_account_token=sa_data["automountServiceAccountToken"],
    )


def get_kubernetes_cluster_role_binding_from_path(path: Path) -> V1ClusterRoleBinding:
    with open(path) as role_binding_file:
        role_binding_data = yaml.safe_load(role_binding_file)

    return V1ClusterRoleBinding(
        api_version=role_binding_data["apiVersion"],
        kind=role_binding_data["kind"],
        metadata=role_binding_data["metadata"],
        role_ref=role_binding_data["roleRef"],
        subjects=role_binding_data["subjects"],
    )


def get_exposed_port(container: DockerContainer, port: int) -> int:
    """
    Use this method instead of DockerContainer.get_exposed_port as it is decorated with wait_container_is_ready
    which we do not want to use as it does not perform a real healthcheck. DockerContainer.get_exposed_port
    also introduces extra "Waiting for container" logs as we might call it multiple times for containers exposing
    multiple ports such as rabbitmq.
    """

    return int(
        container.get_docker_client().port(container.get_wrapped_container().id, port)
    )


def wait_for_http_code(  # noqa: PLR0913, PLR0917
    container: DockerContainer,
    status_code: int,
    port: int = 80,
    path: str = "/",
    scheme: str = "http",
    timeout=None,
    interval=1,
    request_kwargs: dict | None = None,
):
    """
    Wait for a specific http status code.
    Parameters
    ----------
    container : DockerContainer
        Container which is queried for a specific status code.
    status_code : int
        Status code to wait for.
    port : int
        Port to query request on.
    path : str
        Path to use for request. Default is '/'
    scheme : str
        Scheme to use in request query. Default is 'http'
    timeout : float or None
        Number of seconds to wait for the port to be open. Defaults to wait indefinitely.
    interval : float
        Interval at which to poll the port.
    request_kwargs: dict
        kwargs to pass into the request, e.g.: {'verify': False}
    Returns
    -------
    duration : float
        Number of seconds until the check passed.
    """
    if request_kwargs is None:
        request_kwargs = {"timeout": 1.0}
    elif "timeout" not in request_kwargs:
        request_kwargs["timeout"] = 1.0

    start = time.time()
    while True:
        duration = time.time() - start
        dest = "%s://%s:%d%s" % (
            scheme,
            container.get_container_host_ip(),
            int(container.get_exposed_port(port)),
            path,
        )
        res = None
        try:
            res = requests.get(dest, **request_kwargs)
        except requests.RequestException:
            time.sleep(interval)
        if res and res.status_code == status_code:
            return duration
        if timeout and duration > timeout:
            raise TimeoutError(
                "container did not respond with %d listening on port %d in %.3f seconds"
                % (status_code, port, timeout)
            )
