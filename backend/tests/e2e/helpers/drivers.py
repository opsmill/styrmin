"""Publish driver variants to the harness git server, copy driver files into the
Styrmin server and agent pods, and load them through the SDK."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import kr8s.asyncio
import yaml
from dulwich import porcelain
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import ApplicationDriverVersion

from tests.e2e.conftest import _portforward

MISNAMED_DRIVER_NAME = "simple-app-misnamed"
MISNAMED_CONTAINER = "wrong-name"
MISNAMED_BRANCH = "misnamed-container"


async def publish_misnamed_simple_app_driver(
    *,
    client: StyrminClient,
    vcluster: dict,
    git_server: dict[str, str],
    tmp_path: Path,
) -> ApplicationDriverVersion:
    """Load ``simple-app-misnamed``: simple-app whose ``server`` component container is
    ``wrong-name``, a container its chart never renders (018 SC-005)."""
    repo_dir = tmp_path / MISNAMED_DRIVER_NAME
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    git_svc = await AsyncService.get("git-server", namespace="default", api=kr8s_api)
    async with _portforward(git_svc, remote_port=9418) as local_port:
        # Clone the harness copy so the chart location already points at the chart server.
        local_url = f"git://localhost:{local_port}/simple-app.git"
        await asyncio.to_thread(porcelain.clone, local_url, str(repo_dir))

        spec_path = repo_dir / "driver.styrmin.yml"
        spec = yaml.safe_load(spec_path.read_text())
        spec["metadata"]["name"] = MISNAMED_DRIVER_NAME
        spec["spec"]["components"]["server"]["container"] = MISNAMED_CONTAINER
        spec_path.write_text(yaml.dump(spec, default_flow_style=False))

        await asyncio.to_thread(
            porcelain.add, str(repo_dir), paths=["driver.styrmin.yml"]
        )
        await asyncio.to_thread(
            porcelain.commit,
            str(repo_dir),
            message=b"misname the server component container",
            author=b"test <test@test.com>",
            committer=b"test <test@test.com>",
        )
        await asyncio.to_thread(
            porcelain.push,
            str(repo_dir),
            remote_location=local_url,
            refspecs=[f"HEAD:refs/heads/{MISNAMED_BRANCH}".encode()],
            force=True,
        )
    return await client.drivers.load_version(git_server["simple-app"], MISNAMED_BRANCH)


# The container of the Styrmin server pod, and the agent pod and its container
# (helm/styrmin and helm/agent). The agent's Prefect process worker runs every
# action of a driver version.
SERVER_CONTAINER = "styrmin-server"
AGENT_POD_SELECTOR = "app.kubernetes.io/component=agent"
AGENT_CONTAINER = "agent"


def _kubectl_cp(
    kubeconfig: str,
    local: Path,
    pod: str,
    dest: str,
    *,
    container: str = SERVER_CONTAINER,
) -> None:
    """Copy ``local`` into ``<pod>:<dest>`` (recursively for directories)."""
    subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "styrmin",
            "cp",
            "-c",
            container,
            str(local),
            f"{pod}:{dest}",
        ],
        check=True,
    )


def _pod_name(kubeconfig: str, selector: str) -> str:
    """Return the name of the first pod in the ``styrmin`` namespace that ``selector`` selects."""
    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "styrmin",
            "get",
            "pods",
            "-l",
            selector,
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    name = result.stdout.strip()
    assert name, f"no pod {selector} found in vcluster"
    return name


def _styrmin_pod_name(kubeconfig: str) -> str:
    """Return the styrmin-server pod name in the e2e vcluster."""
    return _pod_name(
        kubeconfig, "app.kubernetes.io/component=server,app.kubernetes.io/name=styrmin"
    )


def _agent_pod_name(kubeconfig: str) -> str:
    """Return the agent pod name in the e2e vcluster."""
    return _pod_name(kubeconfig, AGENT_POD_SELECTOR)
