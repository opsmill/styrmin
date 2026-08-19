"""Reusable CLI parameter types and validators."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from cyclopts import Parameter


def validate_uuid(_type: Any, value: Any) -> None:  # noqa: ANN401
    """Validate that a string is a valid UUID."""
    if value is None:
        return
    try:
        uuid.UUID(value)
    except ValueError:
        raise ValueError(f"Invalid UUID: {value!r}") from None


def validate_positive(_type: Any, value: Any) -> None:  # noqa: ANN401
    """Validate that a numeric value is positive (> 0)."""
    if value is None:
        return
    if value <= 0:
        raise ValueError(f"Value must be positive, got {value}")


def validate_directory_exists(_type: Any, value: Any) -> None:  # noqa: ANN401
    """Validate that a path points to an existing directory."""
    if value is None:
        return
    path = Path(value)
    if not path.is_dir():
        if not path.exists():
            raise ValueError(f"Path does not exist: {value!r}")
        raise ValueError(f"Path is not a directory: {value!r}")


# --- Name-based type aliases (positional arguments) ---

ClusterName = Annotated[str | None, Parameter(help="Name of the cluster.")]
EnvironmentName = Annotated[str | None, Parameter(help="Name of the environment.")]
DeploymentName = Annotated[
    str | None,
    Parameter(help="Name of the deployment (resolves its active instance)."),
]

# --- Optional ID flags (--id for backward-compatible UUID access) ---

OptionalClusterId = Annotated[
    str | None,
    Parameter(name="--id", help="UUID of the cluster.", validator=validate_uuid),
]
OptionalEnvironmentId = Annotated[
    str | None,
    Parameter(name="--id", help="UUID of the environment.", validator=validate_uuid),
]
OptionalDeploymentId = Annotated[
    str | None,
    Parameter(name="--id", help="UUID of the deployment (resolves its active instance).", validator=validate_uuid),
]

# --- Environment context flag (disambiguates a deployment name lookup) ---

EnvironmentContextName = Annotated[
    str | None,
    Parameter(name="--environment", help="Environment name to disambiguate the deployment name."),
]

# --- Restore target deployment flags ---

TargetDeploymentName = Annotated[
    str | None,
    Parameter(name="--target-deployment", help="Name of the target deployment (restore into its active instance)."),
]
TargetDeploymentId = Annotated[
    str | None,
    Parameter(
        name="--target-deployment-id",
        help="UUID of the target deployment (restore into its active instance).",
        validator=validate_uuid,
    ),
]

# --- Cluster context flags for environment commands ---

ClusterContextName = Annotated[
    str,
    Parameter(name="--cluster", help="Cluster name (default: 'default')."),
]
ClusterContextId = Annotated[
    str | None,
    Parameter(name="--cluster-id", help="UUID of the cluster.", validator=validate_uuid),
]

# --- UUID type aliases ---
# NOTE: These aliases bake Parameter(help=...) into the type. If a call site
# needs different help text, use a standalone Annotated type there instead.

ClusterId = Annotated[str, Parameter(help="UUID of the cluster.", validator=validate_uuid)]
EnvironmentId = Annotated[str, Parameter(help="UUID of the environment.", validator=validate_uuid)]
DeploymentId = Annotated[str, Parameter(help="UUID of the deployment.", validator=validate_uuid)]
TaskId = Annotated[str, Parameter(help="UUID of the task.", validator=validate_uuid)]
BackupId = Annotated[str, Parameter(help="UUID of the backup.", validator=validate_uuid)]
EnvironmentBackupId = Annotated[str, Parameter(help="UUID of the environment backup.", validator=validate_uuid)]
EnvironmentRestoreId = Annotated[str, Parameter(help="UUID of the environment restore.", validator=validate_uuid)]
EnvironmentCloneId = Annotated[str, Parameter(help="UUID of the environment clone.", validator=validate_uuid)]
BslId = Annotated[str, Parameter(help="UUID of the backup storage location.", validator=validate_uuid)]
RestoreId = Annotated[str, Parameter(help="UUID of the restore operation.", validator=validate_uuid)]
InstanceId = Annotated[str, Parameter(help="UUID of the application instance.", validator=validate_uuid)]

# --- Optional UUID type aliases ---

OptionalInstanceId = Annotated[
    str | None, Parameter(help="UUID of the target application instance.", validator=validate_uuid)
]
InstanceIdOption = Annotated[
    str | None,
    Parameter(
        name="--instance-id",
        help="UUID of a specific application instance (bypasses deployment resolution).",
        validator=validate_uuid,
    ),
]

# --- Numeric type aliases ---

MaxWait = Annotated[float, Parameter(help="Max seconds to wait (with --wait).", validator=validate_positive)]
PollInterval = Annotated[float, Parameter(help="Poll interval in seconds (with --wait).", validator=validate_positive)]
