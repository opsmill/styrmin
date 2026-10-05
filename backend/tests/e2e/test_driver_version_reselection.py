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

Loading that second build must not disturb the first one's actions: each
build keeps its own Prefect deployments, pinned to the commit it was loaded
from (#375).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import kr8s.asyncio
import pytest
import yaml
from dulwich import porcelain
from kr8s.asyncio.objects import Service as AsyncService
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import DeploymentFilter, DeploymentFilterTags
from styrmin_sdk import StyrminClient
from tests.e2e.conftest import _portforward, _wait_for_http
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


async def _assert_actions_pinned(*, vcluster: dict, commits: list[str]) -> None:
    """Each commit has its own action deployments, checking out that commit."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    prefect_service = await AsyncService.get(
        "prefect-server", namespace="styrmin", api=kr8s_api
    )
    async with _portforward(prefect_service, remote_port=4200) as port:
        prefect_url = f"http://localhost:{port}/api"
        await _wait_for_http(f"{prefect_url}/health", timeout=60.0)
        async with PrefectClient(api=prefect_url) as prefect:
            for commit in commits:
                deployments = await prefect.read_deployments(
                    deployment_filter=DeploymentFilter(
                        tags=DeploymentFilterTags(all_=[f"fingerprint/{commit[:7]}"])
                    )
                )
                assert deployments, f"no action deployment for commit {commit[:7]}"
                for deployment in deployments:
                    clone = deployment.pull_steps[0][
                        "prefect.deployments.steps.git_clone"
                    ]
                    assert clone.get("commit_sha") == commit, deployment.name
                    assert not clone.get("branch"), deployment.name


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
    assert deployment.application_driver_version is not None
    original_commit = deployment.application_driver_version.source_commit_sha
    assert original_commit is not None

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

    # Loading the new build left the original's actions in place, and neither
    # build's actions follow the branch tip.
    assert deployment.application_driver_version is not None
    new_commit = deployment.application_driver_version.source_commit_sha
    assert new_commit is not None
    await _assert_actions_pinned(
        vcluster=vcluster, commits=[original_commit, new_commit]
    )

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
