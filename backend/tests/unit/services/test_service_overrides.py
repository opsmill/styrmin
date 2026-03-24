"""Unit tests for service name override validation (T028)."""

from uuid import uuid4

import pytest

from styrmin_backend.services.driver.models.resources.services import (
    ServiceDefinition,
    ServiceKind,
    ServiceScope,
)
from styrmin_backend.services.exceptions import (
    InvalidServiceOverrideError,
    ServiceNameConflictError,
)
from styrmin_backend.services.services_discovery import (
    create_services_for_deployment,
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


class TestValidOverrideApplied:
    @pytest.mark.asyncio
    async def test_override_applied_to_resolved_name(self) -> None:
        uow = _make_uow()
        deployment_id = uuid4()
        env_id = uuid4()
        defs = [_make_service_def(name="infrahub")]
        overrides = {"infrahub": "infrahub-staging"}

        async with uow:
            result = await create_services_for_deployment(
                deployment_id=deployment_id,
                environment_id=env_id,
                service_definitions=defs,
                uow=uow,
                service_name_overrides=overrides,
            )

        assert len(result) == 1
        assert result[0].driver_service_name == "infrahub"
        assert result[0].resolved_name == "infrahub-staging"


class TestOverrideKeyNotMatching:
    @pytest.mark.asyncio
    async def test_invalid_override_key_raises_error(self) -> None:
        uow = _make_uow()
        defs = [_make_service_def(name="infrahub")]
        overrides = {"nonexistent": "something"}

        async with uow:
            with pytest.raises(InvalidServiceOverrideError) as exc_info:
                await create_services_for_deployment(
                    deployment_id=uuid4(),
                    environment_id=uuid4(),
                    service_definitions=defs,
                    uow=uow,
                    service_name_overrides=overrides,
                )

        assert exc_info.value.invalid_service_name == "nonexistent"
        assert "infrahub" in exc_info.value.available_service_names


class TestOverrideCausingConflict:
    @pytest.mark.asyncio
    async def test_override_causing_name_conflict(self) -> None:
        from styrmin_backend.db.models import DeployedService as DSModel

        existing_svc = DSModel(
            id=uuid4(),
            driver_service_name="web",
            resolved_name="taken-name",
            kind="http",
            scope="internal",
            port=8080,
            component="server",
            deployment_id=uuid4(),
            environment_id=uuid4(),
        )
        repo = FakeDeployedServiceRepository(models=[existing_svc])
        uow = _make_uow(deployed_services=repo)
        defs = [_make_service_def(name="api")]
        overrides = {"api": "taken-name"}

        async with uow:
            with pytest.raises(ServiceNameConflictError):
                await create_services_for_deployment(
                    deployment_id=uuid4(),
                    environment_id=existing_svc.environment_id,
                    service_definitions=defs,
                    uow=uow,
                    service_name_overrides=overrides,
                )


class TestPartialOverrides:
    @pytest.mark.asyncio
    async def test_partial_overrides_leave_defaults(self) -> None:
        uow = _make_uow()
        deployment_id = uuid4()
        env_id = uuid4()
        defs = [
            _make_service_def(name="web", port=8080),
            _make_service_def(name="api", port=3000),
        ]
        overrides = {"web": "web-custom"}  # Only override web, not api

        async with uow:
            result = await create_services_for_deployment(
                deployment_id=deployment_id,
                environment_id=env_id,
                service_definitions=defs,
                uow=uow,
                service_name_overrides=overrides,
            )

        assert len(result) == 2
        web = next(s for s in result if s.driver_service_name == "web")
        api = next(s for s in result if s.driver_service_name == "api")
        assert web.resolved_name == "web-custom"
        assert api.resolved_name == "api"  # Kept default


class TestDNSLabelValidationOnOverrides:
    @pytest.mark.asyncio
    async def test_invalid_dns_label_override_rejected(self) -> None:
        uow = _make_uow()
        defs = [_make_service_def(name="web")]
        overrides = {"web": "INVALID_NAME"}

        async with uow:
            with pytest.raises(ValueError, match="DNS label"):
                await create_services_for_deployment(
                    deployment_id=uuid4(),
                    environment_id=uuid4(),
                    service_definitions=defs,
                    uow=uow,
                    service_name_overrides=overrides,
                )
