from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID


class ServiceError(Exception):
    """Base class for exceptions in this module."""

    error_code: str = "OPERATION_FAILED"
    default_message: str = "An operation failed"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.default_message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {}


class NoInstanceError(ServiceError):
    """The application instance was not found."""

    error_code = "NOT_FOUND"
    default_message = "Application instance not found"


class InvalidCredentialsError(ServiceError):
    """Authentication failed: nonexistent user, wrong password, or deactivated account."""

    error_code = "INVALID_CREDENTIALS"
    default_message = "Invalid credentials"


class PasswordPolicyError(ServiceError):
    """Password fails the length policy (12-256 chars)."""

    error_code = "VALIDATION_ERROR"
    default_message = "Password does not meet the password policy"


class ServiceUnexpectedError(ServiceError):
    """An unexpected error occurred."""

    error_code = "INTERNAL_ERROR"
    default_message = "An unexpected error occurred"


class InvalidContextError(ServiceError):
    """The context configuration is invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "The context configuration is invalid"


class ApplicationDriverNotFoundError(ServiceError):
    """The application was not found."""

    error_code = "NOT_FOUND"
    default_message = "Application driver not found"


class ClusterLimitReachedError(ServiceError):
    """The maximum number of clusters has been reached."""

    error_code = "CLUSTER_LIMIT_REACHED"
    default_message = "Only one cluster is allowed. Delete the existing cluster before creating a new one."


class ClusterAlreadyExistsError(ServiceError):
    """The cluster already exists."""

    error_code = "ALREADY_EXISTS"
    default_message = "A cluster with that name already exists"


class ClusterNotFoundError(ServiceError):
    """The cluster was not found."""

    error_code = "NOT_FOUND"
    default_message = "Cluster not found"


class ClusterInUseError(ServiceError):
    """Cannot delete a cluster that still has environments."""

    error_code = "IN_USE"
    default_message = "Cluster still has one or more environments"

    def __init__(
        self, cluster_name: str, environment_names: list[str], message: str = ""
    ) -> None:
        self.environment_names = environment_names
        super().__init__(
            message
            or f"Cluster '{cluster_name}' still has environments: "
            f"{', '.join(environment_names)}. "
            "Delete them before deleting the cluster."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"environment_names": self.environment_names}


class EnvironmentAlreadyExistsError(ServiceError):
    """The environment already exists."""

    error_code = "ALREADY_EXISTS"
    default_message = "An environment with that name already exists"


class EnvironmentNotFoundError(ServiceError):
    """The environment was not found."""

    error_code = "NOT_FOUND"
    default_message = "Environment not found"


class InvalidChartValuesError(ServiceError):
    """The chart values are invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "The chart values are invalid"


class ChartValuesTemplateRenderingError(ServiceError):
    """The chart values are invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "Chart values template rendering failed"


class ApplicationDriverVersionNotFoundError(ServiceError):
    """The application driver version was not found."""

    error_code = "NOT_FOUND"
    default_message = "Application driver version not found"


class ApplicationDriverVersionAlreadyExistsError(ServiceError):
    """The application already exists."""

    error_code = "ALREADY_EXISTS"
    default_message = "The application driver version already exists"


class InstanceNotFoundError(ServiceError):
    """The application instance was not found."""

    error_code = "NOT_FOUND"
    default_message = "Application instance not found"


class InconsistentStateError(ServiceError):
    """The application instance is in an inconsistent state."""

    error_code = "OPERATION_FAILED"
    default_message = "Application instance is in an inconsistent state"


class InvalidVersionError(ServiceError):
    """The version is invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "The version is invalid"


class InvalidVersionSyntaxError(ServiceError):
    """The version syntax is invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "The version syntax is invalid"


class DriverVersionNotFoundError(ServiceError):
    """The pinned application driver version was not found."""

    error_code = "NOT_FOUND"
    default_message = "Application driver version not found"


class UnupgradableApplicationInstanceError(ServiceError):
    """The application instance is not upgradable."""

    error_code = "OPERATION_FAILED"
    default_message = "The application instance is not upgradable"


class TaskNotFoundError(ServiceError):
    """The task was not found."""

    error_code = "NOT_FOUND"
    default_message = "Task not found"


class UnknownTaskStateError(ServiceError):
    """The task state is unknown."""

    error_code = "OPERATION_FAILED"
    default_message = "The task state is unknown"


class InstanceNameUnavailableError(ServiceError):
    """Every generated name for a new instance is already in use."""

    error_code = "OPERATION_FAILED"
    default_message = (
        "Could not find an unused name for the new instance. Retry the operation."
    )


class DeploymentNotFoundError(ServiceError):
    """The deployment was not found."""

    error_code = "NOT_FOUND"
    default_message = "Deployment not found"


class DeploymentRestoringError(ServiceError):
    """Deletion was attempted on a deployment that is currently restoring."""

    error_code = "DEPLOYMENT_RESTORING"
    default_message = (
        "Cannot delete a deployment while a restore is in progress. "
        "Wait for the restore to finish or fail before retrying."
    )


class DeploymentNameValidationError(ServiceError):
    """The deployment name is invalid."""

    error_code = "VALIDATION_ERROR"
    default_message = "The deployment name is invalid"


class DeploymentNameConflictError(ServiceError):
    """A deployment with that name already exists."""

    error_code = "ALREADY_EXISTS"
    default_message = "A deployment with that name already exists"


class IngressControllerNotHealthyError(ServiceError):
    """The ingress controller is not healthy."""

    error_code = "OPERATION_FAILED"
    default_message = "The dedicated ingress controller is not healthy"


class InternalDeploymentError(ServiceError):
    """Operation not allowed on internal deployments."""

    error_code = "OPERATION_DENIED"
    default_message = "Operation not allowed on internal (system-managed) deployments"


class DeletedDeploymentRestoreError(ServiceError):
    """A restore was attempted into a deleted (tombstoned) deployment."""

    error_code = "OPERATION_DENIED"
    default_message = (
        "Cannot restore into a deleted deployment. A deleted deployment's "
        "backups can be listed but not restored."
    )


class ServiceNameConflictError(ServiceError):
    """A service name conflicts with an existing service in the environment."""

    error_code = "ALREADY_EXISTS"
    default_message = "Service name conflicts with an existing service"

    def __init__(
        self,
        message: str = "",
        conflicting_name: str = "",
        existing_deployment_name: str = "",
    ) -> None:
        self.conflicting_name = conflicting_name
        self.existing_deployment_name = existing_deployment_name
        super().__init__(message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "conflicting_name": self.conflicting_name,
            "existing_deployment_name": self.existing_deployment_name,
        }


class InvalidServiceOverrideError(ServiceError):
    """A service name override references a non-existent driver service."""

    error_code = "VALIDATION_ERROR"
    default_message = "Invalid service name override"

    def __init__(
        self,
        message: str = "",
        invalid_service_name: str = "",
        available_service_names: list[str] | None = None,
    ) -> None:
        self.invalid_service_name = invalid_service_name
        self.available_service_names = available_service_names or []
        super().__init__(message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "invalid_service_name": self.invalid_service_name,
            "available_service_names": self.available_service_names,
        }


class BackupNotFoundError(ServiceError):
    """The backup was not found."""

    error_code = "NOT_FOUND"
    default_message = "Backup not found"


class BackupAlreadyInProgressError(ServiceError):
    """A backup is already in progress for this instance."""

    error_code = "ALREADY_IN_PROGRESS"
    default_message = "A backup is already in progress for this instance"

    def __init__(self, existing_backup_id: str, message: str = "") -> None:
        self.existing_backup_id = existing_backup_id
        super().__init__(message or f"Backup already in progress: {existing_backup_id}")

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"existing_backup_id": self.existing_backup_id}


class BackupDuringUpgradeError(ServiceError):
    """Cannot create a backup while an upgrade is in progress."""

    error_code = "ALREADY_IN_PROGRESS"
    default_message = "Cannot create a backup while an upgrade is in progress"


class BackupDeletionError(ServiceError):
    """Failed to delete backup."""

    error_code = "OPERATION_FAILED"
    default_message = "Failed to delete backup"


class RestoreNotFoundError(ServiceError):
    """The restore was not found."""

    error_code = "NOT_FOUND"
    default_message = "Restore not found"


class RestoreAlreadyInProgressError(ServiceError):
    """A restore is already in progress."""

    error_code = "ALREADY_IN_PROGRESS"
    default_message = "A restore is already in progress"

    def __init__(self, existing_restore_id: str, message: str = "") -> None:
        self.existing_restore_id = existing_restore_id
        super().__init__(
            message or f"Restore already in progress: {existing_restore_id}"
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"existing_restore_id": self.existing_restore_id}


class BackupScheduleNotFoundError(ServiceError):
    """The backup schedule was not found."""

    error_code = "NOT_FOUND"
    default_message = "Backup schedule not found"


class EnvironmentBackupNotFoundError(ServiceError):
    """The environment backup was not found."""

    error_code = "NOT_FOUND"
    default_message = "Environment backup not found"


class EnvironmentRestoreNotFoundError(ServiceError):
    """The environment restore was not found."""

    error_code = "NOT_FOUND"
    default_message = "Environment restore not found"


class EnvironmentOperationInProgressError(ServiceError):
    """An environment-level backup or restore is already in progress.

    Only one environment-level operation may be in flight per environment
    (research.md D6). ``operation_kind`` names which one is holding the
    environment: ``"environment_backup"`` or ``"environment_restore"``.
    """

    error_code = "ALREADY_IN_PROGRESS"
    default_message = (
        "An environment-level operation is already in progress for this environment"
    )

    def __init__(
        self, operation_id: str, operation_kind: str, message: str = ""
    ) -> None:
        self.operation_id = operation_id
        self.operation_kind = operation_kind
        super().__init__(
            message or f"An {operation_kind} is already in progress: {operation_id}"
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
        }


class EnvironmentBackupNotRestorableError(ServiceError):
    """The environment backup's derived status does not permit a restore."""

    error_code = "OPERATION_DENIED"
    default_message = (
        "Environment backup is not restorable: its derived status is neither "
        "completed nor partial"
    )


class EnvironmentCloneNotFoundError(ServiceError):
    """The environment clone record was not found.

    Also raised *inside* the clone flow when the record vanished mid-flight:
    deleting the source environment deletes its non-terminal clone records
    (010 research D9), exactly like ``RestoreNotFoundError`` ends the restore
    flow quietly instead of crashing it.
    """

    error_code = "NOT_FOUND"
    default_message = "Environment clone not found"


class EnvironmentBackupInUseByCloneError(ServiceError):
    """Cannot delete an environment backup a clone is still capturing into.

    The guard is scoped to the **capture window** (010 spec FR-008, research
    D9): the only window in which deleting the backup would strand work that
    can no longer be attributed to anything. Once the capture is terminal,
    deletion is allowed on purpose — it is the documented escape hatch for a
    clone whose flow died, and it drives a non-terminal clone to ``FAILED``
    with the deletion attributed.

    Precedent for the shape: :class:`BackupStorageLocationInUseError`.
    """

    error_code = "IN_USE"
    default_message = (
        "Environment backup is in use by a clone whose capture is still in flight"
    )

    def __init__(self, clone_id: str, clone_name: str, message: str = "") -> None:
        self.clone_id = clone_id
        self.clone_name = clone_name
        super().__init__(
            message
            or (
                f"Environment backup is being captured by clone {clone_name!r} "
                f"({clone_id}); it can be deleted once that capture is terminal"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"clone_id": self.clone_id, "clone_name": self.clone_name}


class UnknownEnvironmentConfigFieldError(ServiceError):
    """A named environment-config field does not exist.

    Raised by the clone's config merge when ``clearConfigFields`` names
    something that is not a top-level ``EnvironmentConfig`` field (010
    research D7). The known field names travel in the metadata so the caller
    can render the valid set rather than guessing.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "Unknown environment config field"

    def __init__(
        self, fields: list[str], known_fields: list[str], message: str = ""
    ) -> None:
        self.fields = fields
        self.known_fields = known_fields
        super().__init__(
            message
            or (
                f"Unknown environment config field(s): {', '.join(sorted(fields))}. "
                f"Known fields: {', '.join(sorted(known_fields))}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"fields": self.fields, "known_fields": self.known_fields}


class InvalidCloneDeploymentSelectionError(ServiceError):
    """The requested clone selection names deployments that cannot be cloned.

    The ids are unknown, or belong to another environment (010
    contracts/graphql.md — ``NOT_FOUND``, upfront, zero side effects). A
    selected deployment that exists but is *ineligible* is not an error: it is
    attributed as ``skipped`` on the clone record (spec FR-004).
    """

    error_code = "NOT_FOUND"
    default_message = (
        "One or more selected deployments do not exist in this environment"
    )

    def __init__(self, deployment_ids: list[str], message: str = "") -> None:
        self.deployment_ids = deployment_ids
        super().__init__(
            message
            or (
                "These deployments do not exist in the source environment: "
                f"{', '.join(sorted(deployment_ids))}"
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"deployment_ids": self.deployment_ids}


class BackupScheduleAlreadyExistsError(ServiceError):
    """A backup schedule already exists for this deployment."""

    error_code = "ALREADY_EXISTS"
    default_message = "A backup schedule already exists for this deployment"

    def __init__(self, existing_schedule_id: str, message: str = "") -> None:
        self.existing_schedule_id = existing_schedule_id
        super().__init__(message or f"Schedule already exists: {existing_schedule_id}")

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"existing_schedule_id": self.existing_schedule_id}


class AmbiguousIdentifierError(ServiceError):
    """Both or neither identifier was provided for a resource lookup."""

    error_code = "VALIDATION_ERROR"
    default_message = "Provide either an ID or a name, not both"


class InvalidDeploymentLookupArgsError(ServiceError):
    """The deployment(...) query was called with an invalid argument
    combination.

    Exactly one of ``deploymentId`` (alone) or ``name`` + ``environmentId``
    (together) must be provided.
    """

    error_code = "INVALID_DEPLOYMENT_LOOKUP_ARGS"
    default_message = "specify either deploymentId or (name + environmentId), not both"


class BackupStorageLocationNotFoundError(ServiceError):
    """The backup storage location was not found."""

    error_code = "NOT_FOUND"
    default_message = "Backup storage location not found"


class BackupStorageLocationAlreadyExistsError(ServiceError):
    """A backup storage location with that name already exists."""

    error_code = "ALREADY_EXISTS"
    default_message = "A backup storage location with that name already exists"


class BackupStorageLocationInUseError(ServiceError):
    """Cannot delete a backup storage location that is assigned to environments."""

    error_code = "IN_USE"
    default_message = "Backup storage location is in use by one or more environments"

    def __init__(self, environment_names: list[str], message: str = "") -> None:
        self.environment_names = environment_names
        super().__init__(
            message
            or f"Backup storage location is in use by: {', '.join(environment_names)}"
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"environment_names": self.environment_names}


class InvalidSchedulingConfigError(ServiceError):
    """The scheduling configuration payload failed validation.

    Raised when a level's ``scheduling`` section cannot be parsed into a
    :class:`SchedulingConfig` — typically an unparseable Kubernetes
    quantity, a non-DNS-1123 runtime class, or a structural mistake like
    an affinity term missing both ``label_selector`` and ``deployment_ref``.
    The ``path`` points at the scope that holds the bad payload so the
    API error extension can tell the operator where to look.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "The scheduling configuration is invalid"

    def __init__(self, message: str = "", path: str | None = None) -> None:
        self.path = path
        super().__init__(message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"path": self.path} if self.path is not None else {}


class UnknownComponentInConfigError(ServiceError):
    """A component-level scheduling payload references an undeclared component name.

    Raised when scheduling configuration targets a component that the
    active driver version does not declare. Catching this at config time
    prevents rendering-time surprises where the configured rules silently
    apply to nothing.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "Scheduling configuration references an unknown component"

    def __init__(
        self,
        message: str = "",
        component_name: str = "",
        path: str | None = None,
    ) -> None:
        self.component_name = component_name
        self.path = path
        super().__init__(
            message
            or f"Scheduling configuration references unknown component: {component_name!r}"
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"component_name": self.component_name}
        if self.path is not None:
            meta["path"] = self.path
        return meta


class UnresolvableAffinityReferenceError(ServiceError):
    """A deployment_ref in an affinity term cannot be resolved in the environment.

    Raised when an affinity term's ``deployment_ref`` points at a
    deployment that doesn't exist, lives in a different environment, or is
    tombstoned (``deleted=True``, with the deployment's last name).
    Surfacing the specific identifier and the term's ``path`` lets the
    operator fix the typo/stale reference before Kubernetes sees an
    always-unsatisfied affinity rule.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "Affinity deployment reference cannot be resolved"

    def __init__(
        self,
        message: str = "",
        deployment_id: str | None = None,
        deployment_name: str | None = None,
        path: str | None = None,
        *,
        deleted: bool = False,
    ) -> None:
        self.deployment_id = deployment_id
        self.deployment_name = deployment_name
        self.path = path
        self.deleted = deleted
        super().__init__(message or self._build_message())

    def _build_message(self) -> str:
        if not self.deleted:
            identifier = self.deployment_id or self.deployment_name or "<unspecified>"
            return f"Affinity deployment reference cannot be resolved: {identifier}"
        location = f" at {self.path}" if self.path is not None else ""
        name = (
            repr(self.deployment_name)
            if self.deployment_name is not None
            else "<unknown>"
        )
        return f"Affinity term{location} names deployment {name} ({self.deployment_id}), which was deleted"

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self.deployment_id is not None:
            meta["deployment_id"] = self.deployment_id
        if self.deployment_name is not None:
            meta["deployment_name"] = self.deployment_name
        if self.path is not None:
            meta["path"] = self.path
        if self.deleted:
            meta["deleted"] = True
        return meta


@dataclass
class UnclonedReference:
    """A deployment that affinity terms of a clone name but the clone does not copy.

    ``deployment_id`` is ``None`` for a name, given by a driver version, that no
    deployment of the source environment has.
    """

    deployment_id: UUID | None
    deployment_name: str | None
    paths: list[str] = field(default_factory=list)


class UnclonedDeploymentReferenceError(ServiceError):
    """A clone request copies an affinity term whose deployment it leaves out.

    Raised by ``cloneEnvironment`` before any record or backup is created. Each
    entry gives the named deployment (last name when tombstoned) and the path of
    every term that names it.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "An affinity term names a deployment that the clone does not copy"

    def __init__(self, deployments: list[UnclonedReference], message: str = "") -> None:
        self.deployments = deployments
        names = ", ".join(
            d.deployment_name or str(d.deployment_id) for d in deployments
        )
        super().__init__(
            message or (f"{self.default_message}: {names}" if names else "")
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "deployments": [
                {
                    "deployment_id": (
                        str(d.deployment_id) if d.deployment_id is not None else None
                    ),
                    "deployment_name": d.deployment_name,
                    "paths": list(d.paths),
                }
                for d in self.deployments
            ]
        }


class ValidationError(ServiceError):
    """Generic input validation failure (length, charset, enum).

    Used by admin user / group mutations when a free-form input fails a
    shape constraint that does not have a more specific code.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "Input validation failed"


class UserNotFoundError(ServiceError):
    """The user was not found."""

    error_code = "USER_NOT_FOUND"
    default_message = "User not found"


class GroupNotFoundError(ServiceError):
    """The group was not found."""

    error_code = "GROUP_NOT_FOUND"
    default_message = "Group not found"


class DuplicateUsernameError(ServiceError):
    """A user with that username already exists."""

    error_code = "DUPLICATE_USERNAME"
    default_message = "A user with that username already exists"


class DuplicateGroupNameError(ServiceError):
    """A group with that name already exists."""

    error_code = "DUPLICATE_GROUP_NAME"
    default_message = "A group with that name already exists"


class LastAdminError(ServiceError):
    """The requested change would leave zero active admins."""

    error_code = "LAST_ADMIN"
    default_message = "Operation would leave zero active admins"


class UserHasReferencesError(ServiceError):
    """The user cannot be hard-deleted because foreign-key references exist."""

    error_code = "USER_HAS_REFERENCES"
    default_message = "User has foreign-key references and cannot be deleted"


class ActionsServiceAccountError(ServiceError):
    """A request would give the built-in ``styrmin-actions`` user a password (ADR-059)."""

    error_code = "FORBIDDEN"
    default_message = "The styrmin-actions user cannot have a password"


class PostRenderPatchRenderingError(ServiceError):
    """Failed to serialise a post-renderer patch into YAML.

    Surfaces the failing resource identity (kind + label selector) so the
    deployment status view can point the user at the offending patch.
    """

    error_code = "OPERATION_FAILED"
    default_message = "Failed to serialise post-renderer patch"

    def __init__(
        self,
        message: str = "",
        kind: str | None = None,
        label_selector: str | None = None,
    ) -> None:
        self.kind = kind
        self.label_selector = label_selector
        super().__init__(message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self.kind is not None:
            meta["kind"] = self.kind
        if self.label_selector is not None:
            meta["label_selector"] = self.label_selector
        return meta


class SchedulingPatchRenderingError(PostRenderPatchRenderingError):
    """Failed to serialise a scheduling post-renderer patch into YAML."""

    default_message = "Failed to serialise scheduling post-renderer patch"


ENV_VARS_MIGRATION_GUIDE_URL = (
    "https://styrmin.pages.dev/docs/drivers/migrating-env-vars"
)
CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL = (
    "https://styrmin.pages.dev/docs/drivers/migrating-container-overrides"
)

RetiredTemplateFilter = Literal[
    "component_env_vars", "component_command", "component_args"
]

_RETIRED_FILTER_MIGRATION_GUIDES: dict[RetiredTemplateFilter, str] = {
    "component_env_vars": ENV_VARS_MIGRATION_GUIDE_URL,
    "component_command": CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    "component_args": CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
}


def _retired_filter_message(filter_name: RetiredTemplateFilter, guide: str) -> str:
    if filter_name == "component_env_vars":
        return (
            "The 'component_env_vars' template filter was removed: Styrmin now injects "
            "env vars into each component's declared component container. Deployment "
            "users: upgrade this deployment to a driver version that declares component "
            "containers. Driver authors: remove the filter from values.j2.yml and declare "
            f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
        )
    return (
        f"The '{filter_name}' template filter was removed: Styrmin now applies container "
        "command and args overrides to each component's declared component container. "
        "Deployment users: move this deployment to a driver version that no longer calls "
        "the filter. Driver authors: remove the filter from values.j2.yml and declare "
        f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
    )


def retired_filter_load_message(filter_name: RetiredTemplateFilter, lineno: int) -> str:
    """The message for a driver ``values.j2.yml`` that calls a retired filter at load time."""
    guide = _RETIRED_FILTER_MIGRATION_GUIDES[filter_name]
    applied = (
        "injects env vars into"
        if filter_name == "component_env_vars"
        else "applies container command and args overrides to"
    )
    return (
        f"values.j2.yml line {lineno} calls the '{filter_name}' template filter, which "
        f"was removed: Styrmin now {applied} each component's declared component "
        "container. Remove the filter from values.j2.yml and declare "
        f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
    )


class RetiredTemplateFilterError(ServiceError):
    """A driver values template called a template filter Styrmin removed.

    The message names the filter and its migration guide, because only the message
    survives the StyrminDeployment CR hop (ADR-057 §4).
    """

    error_code = "RETIRED_TEMPLATE_FILTER"
    default_message = _retired_filter_message(
        "component_env_vars", ENV_VARS_MIGRATION_GUIDE_URL
    )

    def __init__(
        self,
        message: str = "",
        filter_name: RetiredTemplateFilter = "component_env_vars",
        migration_guide: str | None = None,
    ) -> None:
        self.filter_name = filter_name
        self.migration_guide = (
            migration_guide or _RETIRED_FILTER_MIGRATION_GUIDES[filter_name]
        )
        super().__init__(
            message or _retired_filter_message(filter_name, self.migration_guide)
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"filter": self.filter_name, "migration_guide": self.migration_guide}
