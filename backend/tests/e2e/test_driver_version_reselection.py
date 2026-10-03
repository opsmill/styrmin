"""E2E: move a deployment across overlapping driver versions (reselection).

Covers the headline flow of driver-version reselection: load a fresher
driver build whose ``supported_versions`` specifier overlaps the one a
deployment is already on, re-run the upgrade at the **same** application
version, and observe the binding move onto the new build (latest-wins).
Then pin back to the original build via the explicit ``driver_version_id``
selector.

Dual-entrypoint: ``upgrade_deployment`` and ``load_driver_version`` are
ScenarioDriver methods, so the ``[ui-chromium]`` variant exercises the
upgrade dialog's driver-version picker end-to-end while ``[api-chromium]``
goes through the SDK. Binding assertions read through the SDK in both modes
(observation, like the kubectl/http checks in ``test_deploy_app.py``).

The second driver build is published by cloning the harness's simple-app
git repo (helm location already rewritten to the in-cluster chart server),
bumping ``spec.version`` to the next integer with the supported range unchanged, and
pushing the commit as a new branch — a distinct provenance fingerprint per
spec 013, hence a second ApplicationDriverVersion row on the same driver.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import kr8s.asyncio
import pytest
import yaml
from dulwich import porcelain
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from tests.e2e.conftest import _portforward
from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_general,
]


async def _publish_next_driver_version(
    *, vcluster: dict, tmp_path: Path, branch: str = "reselect-next"
) -> str:
    """Push the next driver-version build of simple-app to the harness git server.

    Clones the already-rewritten repo from the in-cluster git server (so the
    helm chart location keeps pointing at the chart server), bumps only
    ``spec.version``, and pushes the commit to ``branch``. Returns the branch
    name to load.
    """
    repo_dir = tmp_path / "simple-app-v2"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    git_svc = await AsyncService.get("git-server", namespace="default", api=kr8s_api)
    async with _portforward(git_svc, remote_port=9418) as local_port:
        local_url = f"git://localhost:{local_port}/simple-app.git"
        await asyncio.to_thread(porcelain.clone, local_url, str(repo_dir))

        spec_path = repo_dir / "driver.styrmin.yml"
        spec = yaml.safe_load(spec_path.read_text())
        # Bump relative to the fixture so example-driver version bumps don't break this.
        spec["spec"]["version"] = str(int(spec["spec"]["version"]) + 1)
        # supported_versions intentionally untouched — the overlap is the point.
        spec_path.write_text(yaml.dump(spec, default_flow_style=False))

        await asyncio.to_thread(
            porcelain.add, str(repo_dir), paths=["driver.styrmin.yml"]
        )
        await asyncio.to_thread(
            porcelain.commit,
            str(repo_dir),
            message=b"bump driver version to 2 (same supported range)",
            author=b"test <test@test.com>",
            committer=b"test <test@test.com>",
        )
        await asyncio.to_thread(
            porcelain.push,
            str(repo_dir),
            remote_location=local_url,
            refspecs=[f"HEAD:refs/heads/{branch}".encode()],
        )
    return branch


@pytest.mark.ci
async def test_driver_version_reselection(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    scenario_environment_id: str,
    styrmin_resources: dict,
    git_server: dict[str, str],
    vcluster: dict,
    tmp_path: Path,
) -> None:
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = deployed_simple_app["deployment_id"]
    scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)

    # Snapshot the current binding and application version. The shared
    # session deployment may have been upgraded by a sibling test — the
    # scenario only assumes "running at some 0.x version on some build".
    deployment = await client.deployments.get(deployment_id)
    original_binding = str(deployment.application_driver_version_id)
    app_version = deployment.application_version
    assert app_version is not None

    # Publish the next driver version with the same supported range and load it.
    branch = await _publish_next_driver_version(vcluster=vcluster, tmp_path=tmp_path)
    new_version = await scenario_driver.load_driver_version(
        git_url=git_server["simple-app"], ref=branch
    )
    assert new_version.id != original_binding

    # 1) Latest-wins: re-running the upgrade at the SAME application version
    # moves the binding onto the newly loaded build — the gap this feature
    # closes (previously a no-op while the current build still matched).
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version=app_version
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
    deployment = await client.deployments.get(deployment_id)
    assert str(deployment.application_driver_version_id) == new_version.id
    assert deployment.application_version == app_version

    # 2) Explicit pin: move back onto the original build even though a newer
    # matching build exists.
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id,
        version=app_version,
        driver_version_id=original_binding,
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)
    deployment = await client.deployments.get(deployment_id)
    assert str(deployment.application_driver_version_id) == original_binding
    assert deployment.application_version == app_version
