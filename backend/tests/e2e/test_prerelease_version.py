"""E2E: a prerelease is deployed only from a driver version whose range names one (#591).

A driver version's ``supported_versions`` range matches a prerelease such as
``0.2.0b0`` only if the range itself names a prerelease. The standard drivers'
ranges name none, so Styrmin refused a beta with "Version 1.12.0b0 is not
supported by the application driver infrahub", which gave neither the reason
nor the ranges.

The scenario loads two builds of one application driver, ``simple-app-prerelease``
(simple-app under another name, so the other tests keep the session driver):

1. Build 1 supports ``>=0.1,<1.0``. A request for ``0.2.0b0`` is refused with
   the prerelease explanation and the supported range, and creates no
   deployment.
2. Build 2 supports ``>=0.2.0b0,<0.3``, the range that the driver documentation
   recommends. The same request is accepted, the deployment binds to build 2
   and reaches running with the ``0.2.0b0`` image.

The simple-app values template uses the application version as the image tag,
so the session image ``simple-app:0.1.0`` is re-tagged ``simple-app:0.2.0b0``.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminAPIError

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.helpers.drivers import publish_simple_app_driver_build

pytestmark = [
    pytest.mark.shard_general,
]

DRIVER_NAME = "simple-app-prerelease"
PRERELEASE = "0.2.0b0"
STABLE_ONLY_RANGE = ">=0.1,<1.0"
PRERELEASE_RANGE = ">=0.2.0b0,<0.3"
RUNNING_TIMEOUT = 300.0


@pytest.fixture(scope="module")
def simple_app_prerelease_image(simple_app_image: str) -> Iterator[str]:
    """The session image under the tag of the prerelease; the nodes read the host daemon."""
    target = f"simple-app:{PRERELEASE}"
    subprocess.run(["docker", "tag", simple_app_image, target], check=True)
    yield target
    # Removes only this tag: the session image keeps its own.
    subprocess.run(["docker", "rmi", target], check=False, capture_output=True)


@pytest.fixture(scope="module")
async def prerelease_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    env = await driver.create_environment(
        name=f"prerelease-e2e-{uuid.uuid4().hex[:8]}",
        cluster_id=styrmin_resources["cluster_id"],
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.mark.ci
@pytest.mark.api_only(
    reason="every action goes through the SDK: the test asserts the error text of "
    "a refused request, and the Deploy form has no equivalent assertion"
)
async def test_prerelease_is_refused_until_a_range_names_it(
    prerelease_environment: dict,
    simple_app_prerelease_image: str,
    git_server: dict[str, str],
    vcluster: dict,
    tmp_path: Path,
) -> None:
    client: StyrminClient = prerelease_environment["client"]
    environment_id = prerelease_environment["environment_id"]

    stable_build = await publish_simple_app_driver_build(
        client=client,
        vcluster=vcluster,
        git_server=git_server,
        tmp_path=tmp_path,
        name=DRIVER_NAME,
        branch="prerelease-stable-range",
        driver_version="1",
        supported_versions=STABLE_ONLY_RANGE,
    )
    assert stable_build.application_driver.name == DRIVER_NAME

    # 1) No range names a prerelease: refused, with the reason and the range.
    with pytest.raises(StyrminAPIError) as refused:
        await client.deployments.create(
            driver=DRIVER_NAME,
            version=PRERELEASE,
            environment_id=environment_id,
            name="prerelease-refused",
        )
    message = str(refused.value)
    assert (
        f"Version {PRERELEASE} is not supported by the application driver {DRIVER_NAME}"
    ) in message, message
    assert f"supported ranges: {STABLE_ONLY_RANGE}" in message, message
    assert (
        "a range matches a prerelease only if one of its clauses names a prerelease"
        in message
    ), message
    assert await client.deployments.list(environment_id) == []

    # 2) A second build whose range names the prerelease: the same request works.
    prerelease_build = await publish_simple_app_driver_build(
        client=client,
        vcluster=vcluster,
        git_server=git_server,
        tmp_path=tmp_path,
        name=DRIVER_NAME,
        branch="prerelease-beta-range",
        driver_version="2",
        supported_versions=PRERELEASE_RANGE,
    )
    assert prerelease_build.id != stable_build.id

    task = await client.deployments.create(
        driver=DRIVER_NAME,
        version=PRERELEASE,
        environment_id=environment_id,
        name="prerelease-accepted",
    )
    assert task.deployment_id is not None
    wait = await client.deployments.wait_for_task(task.id, max_wait=RUNNING_TIMEOUT)
    assert not wait.timed_out and wait.failure_reason is None, wait

    created = await client.deployments.get(task.deployment_id)
    assert created.status == "running"
    assert created.application_version == PRERELEASE
    assert str(created.application_driver_version_id) == str(prerelease_build.id)
