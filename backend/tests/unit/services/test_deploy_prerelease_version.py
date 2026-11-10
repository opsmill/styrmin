"""Unit tests for ``deploy_application`` with a prerelease application version (#591).

The driver version declares the range ``>=1.5,<2.0``, which names no
prerelease. A prerelease whose numbers fit the range is accepted, and the
version stored on the deployment is the string the person typed.

``generate_instance_from_deployment`` and ``apply_state`` are patched the way
``test_deploy_skip_initial_reconcile.py`` patches them, so the tests observe the
version choice and not the context resolver or the Prefect dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from packaging.version import InvalidVersion

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.domain.models import Deployment, Instance, Task, TaskType
from styrmin_backend.services import deployment as deployment_service
from styrmin_backend.services.deployment import deploy_application
from tests.unit.services.fakes import FakeUnitOfWork
from tests.unit.services.test_deploy_skip_initial_reconcile import (
    _make_instance,
    _make_uow,
)

DRIVER_NAME = "infrahub"
RANGE = ">=1.5,<2.0"


@pytest.fixture(autouse=True)
def stub_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _generate(
        *,
        deployment: Deployment,
        uow: object,
        release_reference: str | None = None,
        upcoming_deployments: Mapping[UUID, str] | None = None,
    ) -> Instance:
        return _make_instance(deployment)

    async def _apply_state(
        *,
        deployment: Deployment,
        current_instance: Instance | None,
        uow: object,
        task_type: TaskType,
    ) -> Task:
        return Task.create(type=task_type, deployment_id=deployment.id)

    monkeypatch.setattr(
        deployment_service, "generate_instance_from_deployment", _generate
    )
    monkeypatch.setattr(deployment_service, "apply_state", _apply_state)


def _uow_with_default(default_version: str | None) -> tuple[FakeUnitOfWork, UUID]:
    cluster = Cluster(name="test-cluster", config={})
    environment = Environment(name="test-env", cluster_id=cluster.id, config={})
    repository = HelmRepository(url="https://helm.example.com/test")
    chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="name: {{ app.name }}",
        repository_id=repository.id,
    )
    driver = ApplicationDriver(name=DRIVER_NAME)
    driver_version = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version="1.0.0",
        application_supported_versions=RANGE,
        default_version=default_version,
        source_repository="https://example.com/driver",
        helm_chart_id=chart.id,
    )
    driver_version.component_configs = []
    driver.versions = [driver_version]
    uow = _make_uow(
        cluster=cluster,
        environment=environment,
        driver=driver,
        driver_version=driver_version,
        chart=chart,
        repository=repository,
    )
    return uow, environment.id


async def _deploy(
    uow: FakeUnitOfWork,
    environment_id: UUID,
    version: str | None,
    driver_version_id: UUID | None = None,
):
    await deploy_application(
        driver_name=DRIVER_NAME,
        version=version,
        environment_id=environment_id,
        uow=uow,
        created_by_user_id=uuid4(),
        deployment_name="prerelease",
        driver_version_id=driver_version_id,
    )
    stored = await uow.deployments.get_by_name("prerelease", environment_id)
    assert stored is not None
    return stored


class TestDeployApplicationPrereleaseVersion:
    @pytest.mark.anyio
    async def test_typed_prerelease_is_stored_exactly_as_typed(self) -> None:
        """FR-003: ``1.12.0-beta.1`` is not rewritten to ``1.12.0b1``."""
        uow, environment_id = _uow_with_default(None)

        stored = await _deploy(uow, environment_id, "1.12.0-beta.1")

        assert stored.application_version == "1.12.0-beta.1"

    @pytest.mark.anyio
    async def test_prerelease_default_version_is_used_when_no_version_is_given(
        self,
    ) -> None:
        """research D9: a prerelease ``default_version`` that fits is deployed."""
        uow, environment_id = _uow_with_default("1.12.0b0")

        stored = await _deploy(uow, environment_id, None)

        assert stored.application_version == "1.12.0b0"

    @pytest.mark.anyio
    async def test_a_pinned_driver_version_accepts_a_prerelease_that_fits_its_range(
        self,
    ) -> None:
        """The deployment binds the pinned driver version and keeps the typed text.

        A wrong argument order at the ``_ensure_pin_supports_version`` call in
        ``deploy_application`` would raise here instead of creating a deployment.
        """
        uow, environment_id = _uow_with_default(None)
        pinned = uow.application_driver_versions.models[0]

        stored = await _deploy(
            uow, environment_id, "1.12.0-beta.1", driver_version_id=pinned.id
        )

        assert stored.application_driver_version_id == pinned.id
        assert stored.application_version == "1.12.0-beta.1"


class TestDeployApplicationNonPep440Version:
    """FR-006 of #591: a version that is not PEP 440 behaves as before the change.

    ``deploy_application`` raises ``packaging.version.InvalidVersion`` from the
    service function, with and without a pin, and creates nothing. Observed on
    the code at the head of the branch (``uv run pytest``, ``packaging`` 25.0)
    and equal to the outcome of the helpers recorded in
    ``test_driver_version_resolution.py::TestNonPep440VersionBehaviour``.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("pinned", [False, True])
    async def test_latest_raises_invalid_version_and_creates_nothing(
        self, pinned: bool
    ) -> None:
        uow, environment_id = _uow_with_default(None)
        driver_version_id = (
            uow.application_driver_versions.models[0].id if pinned else None
        )

        with pytest.raises(InvalidVersion, match="Invalid version: 'latest'"):
            await _deploy(
                uow, environment_id, "latest", driver_version_id=driver_version_id
            )

        assert await uow.deployments.get_by_name("prerelease", environment_id) is None
