"""Service discovery service layer.

Manages the lifecycle of DeployedService records: creation at deploy time,
reconciliation on upgrade, deletion on undeploy, and uniqueness enforcement.
"""

from uuid import UUID

from loguru import logger

from styrmin_backend.db.models import DeployedService as DeployedServiceModel
from styrmin_backend.domain.models import DeployedService as DeployedServiceEntity
from styrmin_backend.services.driver.models.resources.services import (
    ServiceDefinition,
    validate_dns_label,
)
from styrmin_backend.services.exceptions import (
    InvalidServiceOverrideError,
    ServiceNameConflictError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork


def parse_service_definitions(raw: list[dict] | None) -> list[ServiceDefinition]:
    """Parse raw JSON dicts from database into validated service definitions."""
    if not raw:
        return []
    return [ServiceDefinition.model_validate(d) for d in raw]


async def create_services_for_deployment(
    deployment_id: UUID,
    environment_id: UUID,
    service_definitions: list[ServiceDefinition],
    uow: UnitOfWork,
    service_name_overrides: dict[str, str] | None = None,
) -> list[DeployedServiceEntity]:
    """Create DeployedService records for a new deployment.

    Args:
        deployment_id: The deployment being created.
        environment_id: The environment the deployment belongs to.
        service_definitions: Service definitions from the driver version.
        uow: Unit of work (caller manages the transaction).
        service_name_overrides: Optional mapping of driver_service_name → override name.

    Returns:
        List of created DeployedService domain entities.

    Raises:
        ServiceNameConflictError: If a resolved name is already in use.
        InvalidServiceOverrideError: If an override key doesn't match a driver service.
    """
    overrides = service_name_overrides or {}

    # Validate override keys
    _validate_override_keys(overrides, service_definitions)

    created: list[DeployedServiceEntity] = []
    for svc_def in service_definitions:
        resolved_name = overrides.get(svc_def.name, svc_def.name)

        # Validate DNS label for overridden names
        if svc_def.name in overrides:
            validate_dns_label(resolved_name)

        # Check uniqueness
        await _check_name_uniqueness(
            resolved_name=resolved_name,
            environment_id=environment_id,
            exclude_deployment_id=None,
            uow=uow,
        )

        entity = DeployedServiceEntity.create(
            driver_service_name=svc_def.name,
            resolved_name=resolved_name,
            kind=svc_def.kind.value,
            scope=svc_def.scope.value,
            port=svc_def.port,
            component=svc_def.component,
            deployment_id=deployment_id,
            environment_id=environment_id,
        )

        # Persist as DB model
        await uow.deployed_services.create(
            DeployedServiceModel(
                id=entity.id,
                driver_service_name=entity.driver_service_name,
                resolved_name=entity.resolved_name,
                kind=entity.kind,
                scope=entity.scope,
                port=entity.port,
                component=entity.component,
                deployment_id=entity.deployment_id,
                environment_id=entity.environment_id,
            )
        )
        created.append(entity)

    logger.info(
        "Created {} deployed services for deployment={}",
        len(created),
        deployment_id,
    )
    return created


async def reconcile_services_on_upgrade(
    deployment_id: UUID,
    environment_id: UUID,
    new_service_definitions: list[ServiceDefinition],
    uow: UnitOfWork,
    service_name_overrides: dict[str, str] | None = None,
) -> list[DeployedServiceEntity]:
    """Reconcile DeployedService records when a deployment is upgraded.

    Deletes old services and creates new ones based on the new driver version.
    """
    overrides = service_name_overrides or {}
    _validate_override_keys(overrides, new_service_definitions)

    # Delete existing services for this deployment
    await uow.deployed_services.delete_by_deployment_id(deployment_id)

    # Create new services (uniqueness check excludes this deployment's old records)
    created: list[DeployedServiceEntity] = []
    for svc_def in new_service_definitions:
        resolved_name = overrides.get(svc_def.name, svc_def.name)

        if svc_def.name in overrides:
            validate_dns_label(resolved_name)

        await _check_name_uniqueness(
            resolved_name=resolved_name,
            environment_id=environment_id,
            exclude_deployment_id=deployment_id,
            uow=uow,
        )

        entity = DeployedServiceEntity.create(
            driver_service_name=svc_def.name,
            resolved_name=resolved_name,
            kind=svc_def.kind.value,
            scope=svc_def.scope.value,
            port=svc_def.port,
            component=svc_def.component,
            deployment_id=deployment_id,
            environment_id=environment_id,
        )

        await uow.deployed_services.create(
            DeployedServiceModel(
                id=entity.id,
                driver_service_name=entity.driver_service_name,
                resolved_name=entity.resolved_name,
                kind=entity.kind,
                scope=entity.scope,
                port=entity.port,
                component=entity.component,
                deployment_id=entity.deployment_id,
                environment_id=entity.environment_id,
            )
        )
        created.append(entity)

    logger.info(
        "Reconciled {} deployed services for deployment={}",
        len(created),
        deployment_id,
    )
    return created


async def resolve_service_names(
    deployment_id: UUID,
    environment_id: UUID,
    service_definitions: list[ServiceDefinition],
    uow: UnitOfWork,
    service_name_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Run the checks of :func:`reconcile_services_on_upgrade` without writing anything.

    Returns the resolved name of each driver service.
    """
    overrides = service_name_overrides or {}
    _validate_override_keys(overrides, service_definitions)
    resolved: dict[str, str] = {}
    for svc_def in service_definitions:
        resolved_name = overrides.get(svc_def.name, svc_def.name)
        if svc_def.name in overrides:
            validate_dns_label(resolved_name)
        await _check_name_uniqueness(
            resolved_name=resolved_name,
            environment_id=environment_id,
            exclude_deployment_id=deployment_id,
            uow=uow,
        )
        resolved[svc_def.name] = resolved_name
    return resolved


async def delete_services_for_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> None:
    """Delete all DeployedService records for a deployment."""
    await uow.deployed_services.delete_by_deployment_id(deployment_id)
    logger.info("Deleted deployed services for deployment={}", deployment_id)


def _validate_override_keys(
    overrides: dict[str, str],
    service_definitions: list[ServiceDefinition],
) -> None:
    """Validate that override keys match declared driver service names."""
    if not overrides:
        return
    valid_names = {s.name for s in service_definitions}
    for override_key in overrides:
        if override_key not in valid_names:
            raise InvalidServiceOverrideError(
                message=f"Service name override '{override_key}' does not match "
                f"any declared service. Available: {sorted(valid_names)}",
                invalid_service_name=override_key,
                available_service_names=sorted(valid_names),
            )


async def _check_name_uniqueness(
    resolved_name: str,
    environment_id: UUID,
    exclude_deployment_id: UUID | None,
    uow: UnitOfWork,
) -> None:
    """Check that a resolved service name is unique within the environment."""
    existing = await uow.deployed_services.get_by_resolved_name_and_environment_id(
        resolved_name=resolved_name,
        environment_id=environment_id,
    )
    if existing is not None:
        # Allow if it belongs to the same deployment (during reconciliation)
        if exclude_deployment_id and existing.deployment_id == exclude_deployment_id:
            return
        raise ServiceNameConflictError(
            message=f"Service name '{resolved_name}' already exists in environment",
            conflicting_name=resolved_name,
            existing_deployment_name=str(existing.deployment_id),
        )
