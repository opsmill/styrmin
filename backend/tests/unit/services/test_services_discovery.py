"""Unit tests for ServicesDiscoveryService (T015)."""

from uuid import uuid4

import pytest

from styrmin_backend.services.driver.models.resources.services import (
    ServiceDefinition,
    ServiceKind,
    ServiceScope,
)
from styrmin_backend.services.exceptions import ServiceNameConflictError
from styrmin_backend.services.services_discovery import (
    create_services_for_deployment,
    delete_services_for_deployment,
    parse_service_definitions,
    reconcile_services_on_upgrade,
)
from tests.unit.services.fakes import (
    FakeDeployedServiceRepository,
    FakeUnitOfWork,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmRepositoryRepository,
    FakeHelmChartRepository,
    FakeApplicationRepository,
    FakeApplicationInstanceRepository,
    FakeActionRepository,
    FakeTaskRepository,
)


def _make_uow(
    deployed_services: FakeDeployedServiceRepository | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=deployed_services or FakeDeployedServiceRepository(),
    )


def _make_service_def(
    name: str = "my-svc",
    kind: str = "http",
    scope: str = "internal",
    port: int = 8080,
    component: str = "server",
) -> ServiceDefinition:
    return ServiceDefinition(
        name=name,
        kind=ServiceKind(kind),
        scope=ServiceScope(scope),
        port=port,
        component=component,
    )


class TestCreateServicesForDeployment:
    @pytest.mark.asyncio
    async def test_creates_services(self) -> None:
        uow = _make_uow()
        deployment_id = uuid4()
        env_id = uuid4()
        defs = [_make_service_def(name="web"), _make_service_def(name="api", port=3000)]

        async with uow:
            result = await create_services_for_deployment(
                deployment_id=deployment_id,
                environment_id=env_id,
                service_definitions=defs,
                uow=uow,
            )

        assert len(result) == 2
        assert result[0].driver_service_name == "web"
        assert result[0].resolved_name == "web"
        assert result[1].driver_service_name == "api"

    @pytest.mark.asyncio
    async def test_uniqueness_enforcement(self) -> None:
        """Duplicate resolved name in environment raises ServiceNameConflictError."""
        from styrmin_backend.db.models import DeployedService as DSModel

        existing_svc = DSModel(
            id=uuid4(),
            driver_service_name="web",
            resolved_name="web",
            kind="http",
            scope="internal",
            port=8080,
            component="server",
            deployment_id=uuid4(),
            environment_id=uuid4(),
        )
        repo = FakeDeployedServiceRepository(models=[existing_svc])
        uow = _make_uow(deployed_services=repo)
        defs = [_make_service_def(name="web")]

        async with uow:
            with pytest.raises(ServiceNameConflictError):
                await create_services_for_deployment(
                    deployment_id=uuid4(),
                    environment_id=existing_svc.environment_id,
                    service_definitions=defs,
                    uow=uow,
                )

    @pytest.mark.asyncio
    async def test_no_services_no_error(self) -> None:
        uow = _make_uow()
        async with uow:
            result = await create_services_for_deployment(
                deployment_id=uuid4(),
                environment_id=uuid4(),
                service_definitions=[],
                uow=uow,
            )
        assert result == []


class TestReconcileServicesOnUpgrade:
    @pytest.mark.asyncio
    async def test_reconcile_removes_old_creates_new(self) -> None:
        from styrmin_backend.db.models import DeployedService as DSModel

        deployment_id = uuid4()
        env_id = uuid4()
        old_svc = DSModel(
            id=uuid4(),
            driver_service_name="old-svc",
            resolved_name="old-svc",
            kind="http",
            scope="internal",
            port=8080,
            component="server",
            deployment_id=deployment_id,
            environment_id=env_id,
        )
        repo = FakeDeployedServiceRepository(models=[old_svc])
        uow = _make_uow(deployed_services=repo)
        new_defs = [_make_service_def(name="new-svc", port=9090)]

        async with uow:
            result = await reconcile_services_on_upgrade(
                deployment_id=deployment_id,
                environment_id=env_id,
                new_service_definitions=new_defs,
                uow=uow,
            )

        assert len(result) == 1
        assert result[0].driver_service_name == "new-svc"
        # Old service should be deleted, new one created
        services_in_repo = await repo.get_by_deployment_id(deployment_id)
        assert len(services_in_repo) == 1
        assert services_in_repo[0].resolved_name == "new-svc"


class TestDeleteServicesForDeployment:
    @pytest.mark.asyncio
    async def test_deletes_services(self) -> None:
        from styrmin_backend.db.models import DeployedService as DSModel

        deployment_id = uuid4()
        svc = DSModel(
            id=uuid4(),
            driver_service_name="web",
            resolved_name="web",
            kind="http",
            scope="internal",
            port=8080,
            component="server",
            deployment_id=deployment_id,
            environment_id=uuid4(),
        )
        repo = FakeDeployedServiceRepository(models=[svc])
        uow = _make_uow(deployed_services=repo)

        async with uow:
            await delete_services_for_deployment(
                deployment_id=deployment_id,
                uow=uow,
            )

        remaining = await repo.get_by_deployment_id(deployment_id)
        assert len(remaining) == 0


class TestParseServiceDefinitions:
    def test_parse_valid(self) -> None:
        raw = [
            {
                "name": "web",
                "kind": "http",
                "scope": "internal",
                "port": 8080,
                "component": "server",
            }
        ]
        result = parse_service_definitions(raw)
        assert len(result) == 1
        assert result[0].name == "web"

    def test_parse_none(self) -> None:
        assert parse_service_definitions(None) == []

    def test_parse_empty(self) -> None:
        assert parse_service_definitions([]) == []
