"""Shared provisioning for the configuration-drawer E2E modules.

Each module declares its simple-app deployment as ``DRAWER_DEPLOYMENT``; all
selected modules' deployments are created concurrently through the SDK.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import DeploymentConfigInput

from tests.e2e.drivers.api_driver import ApiScenarioDriver

RECONCILE_TIMEOUT_SECONDS = 480.0


@dataclass(frozen=True)
class DrawerDeployment:
    """A module's simple-app deployment; ``config`` is seeded at create time."""

    name: str
    config: DeploymentConfigInput | None = None


def _is_skipped(item: pytest.Item) -> bool:
    if item.get_closest_marker("skip") is not None:
        return True
    return any(
        mark.args and mark.args[0] is True for mark in item.iter_markers("skipif")
    )


async def _provision(
    client: StyrminClient, cluster_id: str, spec: DrawerDeployment
) -> dict:
    env = await client.environments.create(
        name=f"{spec.name}-{uuid.uuid4().hex[:8]}", cluster_id=cluster_id, config={}
    )
    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=str(env.id),
        name=spec.name,
        config=spec.config,
    )
    if task.deployment_id is None:
        raise RuntimeError(f"deploy of {spec.name!r} returned no deployment_id")
    deployment_id = str(task.deployment_id)
    await ApiScenarioDriver(client).wait_for_deployment_running(
        deployment_id=deployment_id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    return {
        "environment_id": str(env.id),
        "deployment_id": deployment_id,
        "namespace": f"styrmin-{deployment_id}",
    }


@pytest.fixture(scope="package")
async def drawer_deployments(
    request: pytest.FixtureRequest,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict[str, dict | BaseException]:
    """Provision every selected, non-skipped module's deployment at once.

    Failures stay per module, so one bad provisioning errors only its own tests.
    """
    specs = {
        spec.name: spec
        for item in request.session.items
        if not _is_skipped(item)
        and (spec := getattr(item.module, "DRAWER_DEPLOYMENT", None)) is not None
    }
    client: StyrminClient = styrmin_resources["client"]
    results = await asyncio.gather(
        *(
            _provision(client, styrmin_resources["cluster_id"], spec)
            for spec in specs.values()
        ),
        return_exceptions=True,
    )
    return {
        name: result
        if isinstance(result, BaseException)
        else {
            **result,
            "client": client,
            "kubeconfig_path": vcluster["kubeconfig_path"],
        }
        for name, result in zip(specs, results)
    }


@pytest.fixture(scope="module")
def drawer_deployment(
    request: pytest.FixtureRequest,
    drawer_deployments: dict[str, dict | BaseException],
) -> dict:
    """The requesting module's provisioned deployment (see ``DRAWER_DEPLOYMENT``)."""
    provisioned = drawer_deployments[request.module.DRAWER_DEPLOYMENT.name]
    if isinstance(provisioned, BaseException):
        raise provisioned
    return provisioned
