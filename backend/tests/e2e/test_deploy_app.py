import asyncio
import time

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_general,
]


@pytest.mark.ci
async def test_deploy_simple_app(
    deployed_simple_app: dict,
    vcluster: dict,
) -> None:
    # Read-only observation of a running simple-app. Reuses the session-
    # scoped deployment (parametrized by driver_mode via
    # ``session_scenario_driver``) instead of deploying per-test — a deploy
    # costs ~30–60s and this test doesn't mutate the running state.
    kubeconfig_path = vcluster["kubeconfig_path"]
    namespace = deployed_simple_app["namespace"]

    # External-state assertion — identical across both entrypoints.
    # Target the driver's default service name directly; fuzzy substring
    # match picks up cross-namespace ``ExternalName`` aliases from other
    # tests' deployments that share the env.
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        "simple-app", namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, "simple-app service not found"

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        # Wait for the simple-app to be reachable
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=10.0,
            interval=3.0,
        )

        # Check the /count endpoint
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"http://localhost:{local_port}/count", timeout=10
            )
            assert response.status_code == 200


@pytest.mark.ci
async def test_upgrade_simple_app(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    simple_app_image_v2: str,  # noqa: ARG001 — v0.2.0 image
    vcluster: dict,
) -> None:
    # Upgrade the shared session deployment in place. ``upgrade_deployment``
    # is idempotent — if another test already bumped the version, this is a
    # no-op and we go straight to the /version check.
    deployment_id = deployed_simple_app["deployment_id"]
    namespace = deployed_simple_app["namespace"]
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

    kubeconfig_path = vcluster["kubeconfig_path"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    simple_app_svc = await AsyncService.get(
        "simple-app", namespace=namespace, api=kr8s_api
    )
    assert simple_app_svc is not None, "simple-app service not found"

    async with _portforward(simple_app_svc, remote_port=8000) as local_port:
        await _wait_for_http(
            f"http://localhost:{local_port}/health",
            timeout=60.0,
            interval=3.0,
        )

        # The operator flips displayState=Running once HelmRelease is Ready,
        # which does not wait for the k8s rolling update to complete. Port-
        # forward may hit an old v0.1.0 pod still in the Service endpoints
        # until the rollout finishes, and requests in flight while a pod
        # terminates surface as ``RemoteProtocolError`` / ``ReadError`` /
        # ``ConnectError``. Poll until the Service returns the new version,
        # treating transport errors as "try again".
        deadline = time.time() + 120.0
        last_version: str | None = None
        async with httpx.AsyncClient() as http_client:
            while time.time() < deadline:
                try:
                    response = await http_client.get(
                        f"http://localhost:{local_port}/version", timeout=10
                    )
                except httpx.HTTPError:
                    await asyncio.sleep(3.0)
                    continue
                if response.status_code != 200:
                    await asyncio.sleep(3.0)
                    continue
                last_version = response.json()["version"]
                if last_version == "0.2.0":
                    break
                await asyncio.sleep(3.0)
            assert last_version == "0.2.0", (
                f"Service still serving {last_version!r} after 120s; "
                "rolling update to 0.2.0 did not complete"
            )


@pytest.mark.api_only(
    reason=(
        "Asserts createdBy attribution by reading the deployment through the SDK; "
        "no UI flow exercised — the [ui-chromium] variant would just re-run the "
        "same SDK call."
    ),
)
@pytest.mark.ci
async def test_deployment_records_created_by(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Issue #190: createDeployment records the calling user as
    ``Deployment.createdBy``. The session-scoped client is the seeded
    admin (per ``authenticated_styrmin_client``), so ``createdBy`` should
    surface that user's id and username through the SDK projection.
    """
    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    deployment = await client.deployments.get(deployment_id)
    me = await client.auth.current_user()
    assert me is not None, "session client must be authenticated"
    assert deployment.created_by is not None
    assert deployment.created_by.id == me.id
    assert deployment.created_by.username == me.username
    assert deployment.created_by.display_name == me.display_name


@pytest.mark.ci
async def test_deployed_service_external_url_includes_port(
    deployed_simple_app: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> None:
    """Deployed services expose URL fields that reflect the cluster's configured
    external scheme/port.

    The session fixture configures the cluster with
    ``external_url_scheme=http`` / ``external_url_port=8080`` (matching the
    one-command demo on macOS where Traefik is reached via ``kubectl
    port-forward 8080:80``). Without these fields the frontend would render
    ``http://<host>`` (no port), which is unreachable.
    """
    _, client = session_scenario_driver
    deployment_id = deployed_simple_app["deployment_id"]

    deployment = await client.deployments.get(deployment_id)

    assert deployment.deployed_services, (
        "simple-app should expose at least one deployed service"
    )
    for svc in deployment.deployed_services:
        # Both URL forms must include the cluster's configured external port
        # so the rendered link is actually reachable from a browser on the host.
        assert svc.primary_url is not None, (
            f"primary_url should be populated for service {svc.driver_service_name!r}"
        )
        assert svc.primary_url.startswith("http://"), (
            f"primary_url should use the configured http scheme, got: {svc.primary_url}"
        )
        assert svc.primary_url.endswith(":8080"), (
            f"primary_url should include the cluster's external port (8080), got: {svc.primary_url}"
        )
        if svc.human_readable_url is not None:
            assert svc.human_readable_url.endswith(":8080"), (
                f"human_readable_url should include the cluster's external port (8080), got: {svc.human_readable_url}"
            )
