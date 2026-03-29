from __future__ import annotations

from typing import Any


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


class DeploymentNotFoundError(ServiceError):
    """The deployment was not found."""

    error_code = "NOT_FOUND"
    default_message = "Deployment not found"


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
