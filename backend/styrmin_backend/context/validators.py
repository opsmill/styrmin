from pydantic import ValidationError

from styrmin_backend.context.exceptions import (
    InvalidClusterContextError,
    InvalidDeploymentContextError,
    InvalidEnvironmentContextError,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
)


def validate_cluster_config(context: dict) -> None:
    """Validate the cluster context.

    Raises:
        InvalidClusterContextError: If the cluster context is invalid.
    """

    try:
        ClusterConfig(**context)
    except ValidationError as e:
        # Carry Pydantic's message forward: field-level rules (e.g.
        # ``backup_ttl``, 016 / FR-004) state which field failed and how to
        # fix it, and that hint is the whole value of the error to the caller.
        raise InvalidClusterContextError(str(e)) from e


def validate_environment_config(context: dict) -> None:
    """Validate the environment context.

    Raises:
        InvalidEnvironmentContextError: If the environment context is invalid.
    """

    try:
        EnvironmentConfig(**context)
    except ValidationError as e:
        raise InvalidEnvironmentContextError(str(e)) from e


def validate_deployment_config(context: dict) -> None:
    """Validate the instance context.

    Raises:
        InvalidInstanceContextError: If the instance context is invalid.
    """

    try:
        DeploymentConfig(**context)
    except ValidationError as e:
        raise InvalidDeploymentContextError(str(e)) from e
