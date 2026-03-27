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
    if value <= 0:
        raise ValueError(f"Value must be positive, got {value}")


def validate_directory_exists(_type: Any, value: Any) -> None:  # noqa: ANN401
    """Validate that a path points to an existing directory."""
    path = Path(value)
    if not path.is_dir():
        if not path.exists():
            raise ValueError(f"Path does not exist: {value!r}")
        raise ValueError(f"Path is not a directory: {value!r}")


# --- UUID type aliases ---

ClusterId = Annotated[str, Parameter(help="UUID of the cluster.", validator=validate_uuid)]
EnvironmentId = Annotated[str, Parameter(help="UUID of the environment.", validator=validate_uuid)]
DeploymentId = Annotated[str, Parameter(help="UUID of the deployment.", validator=validate_uuid)]
TaskId = Annotated[str, Parameter(help="UUID of the task.", validator=validate_uuid)]
BackupId = Annotated[str, Parameter(help="UUID of the backup.", validator=validate_uuid)]
BslId = Annotated[str, Parameter(help="UUID of the backup storage location.", validator=validate_uuid)]
RestoreId = Annotated[str, Parameter(help="UUID of the restore operation.", validator=validate_uuid)]
InstanceId = Annotated[str, Parameter(help="UUID of the application instance.", validator=validate_uuid)]

# --- Numeric type aliases ---

MaxWait = Annotated[float, Parameter(help="Max seconds to wait (with --wait).", validator=validate_positive)]
PollInterval = Annotated[float, Parameter(help="Poll interval in seconds (with --wait).", validator=validate_positive)]
