from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.api.definitions.deployment.model import Deployment, EnvVar
from styrmin_backend.api.scalars import JSON
from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.db.models import Deployment as DeploymentDBModel
from styrmin_backend.db.models import Environment as EnvironmentModel

if TYPE_CHECKING:
    from styrmin_backend.api.definitions.backup_storage_location.model import (
        BackupStorageLocation,
    )
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentState as DeploymentStateEntity
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity


def _db_deployment_to_domain(db_deployment: DeploymentDBModel) -> DeploymentEntity:
    """Convert a DB deployment model to a domain entity for GraphQL."""
    entity = DeploymentEntity(
        id=db_deployment.id,
        name=db_deployment.name,
        application_version=db_deployment.application_version,
        config=db_deployment.config,
        parameters=db_deployment.parameters or {},
        application_driver_version_id=db_deployment.application_driver_version_id,
        environment_id=db_deployment.environment_id,
        status=DeploymentStateEntity(db_deployment.status.value),
        deleted_at=db_deployment.deleted_at,
        created_by_user_id=db_deployment.created_by_user_id,
    )
    for component in db_deployment.components:
        entity.add_component(
            ComponentEntity(
                id=component.id,
                name=component.name,
                enabled=component.enabled,
                config=component.config,
            )
        )
    active_instance = db_deployment.active_application_instance
    if active_instance is not None:
        from styrmin_backend.context.models.contexts import GlobalContext

        entity.set_active_instance(
            InstanceEntity(
                id=active_instance.id,
                name=active_instance.name,
                application_version=active_instance.application_version,
                status=InstanceStatusEntity(active_instance.status.value),
                context=GlobalContext.model_validate(active_instance.context),
                application_driver_version_id=active_instance.application_driver_version_id,
                deployment_id=db_deployment.id,
            )
        )
    return entity


@strawberry.type
class Environment:
    id: UUID
    name: str
    config: JSON
    capabilities: JSON

    instance: strawberry.Private[EnvironmentModel]

    @strawberry.field
    def cluster(self) -> Cluster:
        return Cluster.from_instance(self.instance.cluster)

    @strawberry.field
    def backup_storage_location(
        self,
    ) -> (
        Annotated[
            "BackupStorageLocation",
            strawberry.lazy(
                "styrmin_backend.api.definitions.backup_storage_location.model"
            ),
        ]
        | None
    ):
        from styrmin_backend.api.definitions.backup_storage_location.model import (
            BackupStorageLocation,
        )

        if self.instance.backup_storage_location is None:
            return None
        return BackupStorageLocation.from_instance(
            self.instance.backup_storage_location
        )

    @strawberry.field(
        description=(
            "Env vars set at the environment scope. Empty when none are set.\n\n"
            "WARNING: This surface is for non-secret values only. The platform "
            "stores values in plaintext and exposes them through any query that "
            "selects them. Do not store credentials, API keys, or other secret "
            "material here — use the dedicated secret env var path (separate "
            "ticket) once available."
        )
    )
    def env_vars(self) -> list[EnvVar]:
        """Resolve the effective environment-scope env vars.

        Reads ``config.env_vars`` from the persisted environment config and
        validates it through :class:`EnvironmentConfig` so the same Pydantic
        rules that gate the write path apply on the read projection too.
        Empty / unset configs surface as an empty list (FR-020).
        """
        raw_config = self.instance.config
        if not raw_config:
            return []
        env_cfg = EnvironmentConfig.model_validate(raw_config)
        env_vars_dict = env_cfg.env_vars or {}
        return [EnvVar(name=k, value=v) for k, v in env_vars_dict.items()]

    @strawberry.field
    def deployments(self, include_deleted: bool = False) -> list[Deployment]:
        """List deployments in this environment.

        By default, tombstoned deployments (``deleted_at IS NOT NULL``) are
        excluded. Pass ``includeDeleted: true`` to surface them — they
        appear with a non-null ``deletedAt`` field. ``DELETING`` rows have
        ``deleted_at IS NULL`` until the terminal ``DELETED`` transition,
        so they remain visible by default.
        """
        return [
            Deployment.from_instance(_db_deployment_to_domain(deployment))
            for deployment in self.instance.deployments
            if include_deleted or deployment.deleted_at is None
        ]

    @classmethod
    def from_instance(cls, instance: EnvironmentModel) -> Environment:
        return cls(
            id=instance.id,
            name=instance.name,
            instance=instance,
            config=instance.config or {},
            capabilities=instance.capabilities or {},
        )
