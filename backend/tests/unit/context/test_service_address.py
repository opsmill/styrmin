"""The address of a service with and without a service ingress override (#598, T008).

Written before the implementation (Constitution V). The spec fixes what the function returns
(``research.md`` D-007, ``data-model.md`` "Derived: effective address of a service") and does not fix its
name or signature. This file assumes the following, and the implementation task (T013) may change the
``_address`` helper below and nothing else if it names things differently:

.. code-block:: python

    # styrmin_backend/context/fqdn.py
    compute_service_address(
        config: ResolvedConfig,            # the resolved class and suffix
        override: ServiceConfigBlock | None,
        *,
        service_host: str,                 # the resolved service name
        environment_name: str,
        app_name: str,
        deployment_id: str | UUID,
    ) -> ServiceAddress                    # .ingress_class .fqdn_suffix .human_readable_fqdn
                                           # .primary_fqdn .overridden

The cross-deployment test goes through ``generate_context_from_deployment`` and assumes that the
``deployed_services`` entries of the context gain the keys ``driver_service_name``, ``scope``,
``ingress_class`` and ``fqdn_suffix`` (T015; ``driver_service_name`` is needed to name the Ingress, D-005).

Every test resolves the planned symbol inside the test, so a missing symbol fails that test with an
``AttributeError`` and does not break the collection of the rest of the suite.
"""

from __future__ import annotations

import importlib
from typing import Any
from uuid import UUID, uuid4

import pytest

from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.context.models.config import ResolvedConfig
from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    DeployedService,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.context import generate_context_from_deployment
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)

_SUFFIX = "test.styrmin.com"
_OVERRIDE_SUFFIX = "tailnet.example.ts.net"
_DEPLOYMENT_ID = UUID("00000000-0000-0000-0000-000000000042")


def _override(**fields: str | None) -> Any:  # noqa: ANN401
    # Resolved at run time: a missing planned symbol raises ``AttributeError`` in the test that needs it.
    block_cls = importlib.import_module(
        "styrmin_backend.context.models.config"
    ).ServiceConfigBlock
    return block_cls(**fields)


def _address(
    *,
    override: Any = None,  # noqa: ANN401
    ingress_class: str | None = "traefik",
    fqdn_suffix: str | None = _SUFFIX,
    service_host: str = "web",
    environment_name: str = "test",
    app_name: str = "testapp",
    deployment_id: str | UUID = _DEPLOYMENT_ID,
) -> Any:  # noqa: ANN401
    compute_service_address = importlib.import_module(
        "styrmin_backend.context.fqdn"
    ).compute_service_address
    return compute_service_address(
        ResolvedConfig(ingress_class=ingress_class, fqdn_suffix=fqdn_suffix),
        override,
        service_host=service_host,
        environment_name=environment_name,
        app_name=app_name,
        deployment_id=deployment_id,
    )


_PRIMARY = compute_primary_fqdn("testapp", _DEPLOYMENT_ID, _SUFFIX)
_READABLE = compute_human_readable_fqdn("web", "test", _SUFFIX)
_READABLE_OVERRIDDEN = compute_human_readable_fqdn("web", "test", _OVERRIDE_SUFFIX)


class TestWithoutAnOverride:
    def test_the_resolved_class_and_suffix_apply(self) -> None:
        address = _address()

        assert address.ingress_class == "traefik"
        assert address.fqdn_suffix == _SUFFIX
        assert address.overridden is False

    def test_the_hosts_are_built_from_the_resolved_suffix(self) -> None:
        address = _address()

        assert address.human_readable_fqdn == _READABLE == "web-test.test.styrmin.com"
        assert address.primary_fqdn == _PRIMARY

    def test_no_resolved_class_gives_none(self) -> None:
        assert _address(ingress_class=None).ingress_class is None

    @pytest.mark.parametrize("suffix", [None, ""])
    def test_no_suffix_gives_no_host(self, suffix: str | None) -> None:
        address = _address(fqdn_suffix=suffix)

        assert address.human_readable_fqdn is None
        assert address.primary_fqdn is None

    def test_a_block_with_both_fields_none_is_no_override(self) -> None:
        address = _address(override=_override())

        assert address.overridden is False
        assert address.ingress_class == "traefik"
        assert address.human_readable_fqdn == _READABLE


class TestWithAnOverride:
    def test_the_override_class_and_suffix_apply(self) -> None:
        address = _address(
            override=_override(ingress_class="tailscale", fqdn_suffix=_OVERRIDE_SUFFIX)
        )

        assert address.ingress_class == "tailscale"
        assert address.fqdn_suffix == _OVERRIDE_SUFFIX
        assert address.overridden is True

    def test_the_override_suffix_is_in_the_readable_host(self) -> None:
        address = _address(
            override=_override(ingress_class="tailscale", fqdn_suffix=_OVERRIDE_SUFFIX)
        )

        assert address.human_readable_fqdn == _READABLE_OVERRIDDEN
        assert address.human_readable_fqdn == "web-test.tailnet.example.ts.net"

    def test_the_primary_fqdn_is_unchanged(self) -> None:
        """research D-003: the application address keeps the resolved suffix."""
        address = _address(
            override=_override(ingress_class="tailscale", fqdn_suffix=_OVERRIDE_SUFFIX)
        )

        assert address.primary_fqdn == _PRIMARY

    def test_a_class_only_override_keeps_the_resolved_suffix(self) -> None:
        address = _address(override=_override(ingress_class="tailscale"))

        assert address.ingress_class == "tailscale"
        assert address.fqdn_suffix == _SUFFIX
        assert address.human_readable_fqdn == _READABLE
        assert address.overridden is True

    def test_a_suffix_only_override_keeps_the_resolved_class(self) -> None:
        address = _address(override=_override(fqdn_suffix=_OVERRIDE_SUFFIX))

        assert address.ingress_class == "traefik"
        assert address.human_readable_fqdn == _READABLE_OVERRIDDEN
        assert address.overridden is True

    def test_an_override_class_applies_when_no_class_resolves(self) -> None:
        address = _address(ingress_class=None, override=_override(ingress_class="ts"))

        assert address.ingress_class == "ts"

    def test_an_override_suffix_gives_a_readable_host_when_no_suffix_resolves(
        self,
    ) -> None:
        """The primary FQDN has no suffix to use: it stays ``None``."""
        address = _address(
            fqdn_suffix=None, override=_override(fqdn_suffix=_OVERRIDE_SUFFIX)
        )

        assert address.human_readable_fqdn == _READABLE_OVERRIDDEN
        assert address.primary_fqdn is None


class TestServiceOfAnotherDeployment:
    """FR-006, critique E2: a service of another deployment uses its owner's override.

    ``generate_context_from_deployment`` builds ``services`` for every service of the environment.
    It must read the owning deployment's override, and must not apply the current deployment's
    override to a service that the current deployment does not own.
    """

    @pytest.mark.anyio
    async def test_a_peer_service_uses_the_override_of_its_owner(self) -> None:
        uow, environment_id, driver_version_id = await _seed_environment()
        current = await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="executor",
            resolved_name="executor",
            scope="external",
        )
        await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="intent",
            resolved_name="intent-renamed",
            scope="external",
            config={
                "services": {
                    "intent": {
                        "ingress_class": "tailscale",
                        "fqdn_suffix": _OVERRIDE_SUFFIX,
                    }
                }
            },
        )

        context = await generate_context_from_deployment(current, uow)

        peer = context.services["intent"]
        assert peer["human_readable_fqdn"] == compute_human_readable_fqdn(
            "intent-renamed", "test-env", _OVERRIDE_SUFFIX
        )
        assert peer["ingress_class"] == "tailscale"
        assert peer["overridden"] is True
        own = context.services["executor"]
        assert own["human_readable_fqdn"] == compute_human_readable_fqdn(
            "executor", "test-env", _SUFFIX
        )
        assert own["overridden"] is False

    @pytest.mark.anyio
    async def test_the_override_of_the_current_deployment_is_not_applied_to_a_peer(
        self,
    ) -> None:
        uow, environment_id, driver_version_id = await _seed_environment()
        current = await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="executor",
            resolved_name="executor",
            scope="external",
            # Keyed by a driver service name that only the peer declares.
            config={
                "services": {
                    "executor": {"fqdn_suffix": _OVERRIDE_SUFFIX},
                    "intent": {"fqdn_suffix": "wrong.example.com"},
                }
            },
        )
        await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="intent",
            resolved_name="intent",
            scope="external",
        )

        context = await generate_context_from_deployment(current, uow)

        assert context.services["executor"]["overridden"] is True
        assert context.services["intent"]["overridden"] is False
        assert context.services["intent"][
            "human_readable_fqdn"
        ] == compute_human_readable_fqdn("intent", "test-env", _SUFFIX)

    @pytest.mark.anyio
    async def test_deployed_services_entries_carry_scope_and_the_effective_address(
        self,
    ) -> None:
        uow, environment_id, driver_version_id = await _seed_environment()
        current = await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="executor",
            resolved_name="executor",
            scope="external",
            config={
                "services": {
                    "executor": {
                        "ingress_class": "tailscale",
                        "fqdn_suffix": _OVERRIDE_SUFFIX,
                    }
                }
            },
        )
        await _seed_deployment(
            uow,
            environment_id,
            driver_version_id,
            driver_service_name="intent",
            resolved_name="intent",
            scope="internal",
        )

        context = await generate_context_from_deployment(current, uow)

        by_driver_name = {
            e["driver_service_name"]: e for e in context.deployed_services
        }
        assert by_driver_name["executor"]["scope"] == "external"
        assert by_driver_name["executor"]["ingress_class"] == "tailscale"
        assert by_driver_name["executor"]["fqdn_suffix"] == _OVERRIDE_SUFFIX
        assert by_driver_name["intent"]["scope"] == "internal"


def _make_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationDriverVersionRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=FakeDeployedServiceRepository(),
        deployments=FakeDeploymentRepository(),
        application_drivers=FakeApplicationRepository(),
    )


async def _seed_environment() -> tuple[FakeUnitOfWork, UUID, UUID]:
    """One cluster with an FQDN suffix, one environment and one driver version."""
    uow = _make_uow()
    cluster = Cluster(
        name="test-cluster", config={"fqdn_suffix": _SUFFIX, "ingress_class": "traefik"}
    )
    await uow.clusters.create(cluster)
    environment = Environment(name="test-env", cluster_id=cluster.id)
    await uow.environments.create(environment)

    helm_repo = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repo)
    helm_chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    await uow.helm_charts.create(helm_chart)

    app_driver = ApplicationDriver(name="test-app")
    driver_version = ApplicationDriverVersion(
        id=uuid4(),
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        helm_chart_id=helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
        services=[],
        component_configs=[],
    )
    driver_version.application_driver = app_driver
    await uow.application_driver_versions.create(driver_version)
    await uow.application_drivers.create(app_driver)
    return uow, environment.id, driver_version.id


async def _seed_deployment(
    uow: FakeUnitOfWork,
    environment_id: UUID,
    driver_version_id: UUID,
    *,
    driver_service_name: str,
    resolved_name: str,
    scope: str,
    config: dict[str, Any] | None = None,
) -> Deployment:
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=driver_version_id,
        environment_id=environment_id,
        created_by_user_id=uuid4(),
        name=f"deploy-{driver_service_name}",
        config=config,
    )
    deployment.set_status(DeploymentState.RUNNING)
    await uow.deployments.save(deployment)
    await uow.deployed_services.create(
        DeployedService(
            id=uuid4(),
            driver_service_name=driver_service_name,
            resolved_name=resolved_name,
            kind="http",
            scope=scope,
            port=8080,
            component="server",
            deployment_id=deployment.id,
            environment_id=environment_id,
        )
    )
    return deployment
